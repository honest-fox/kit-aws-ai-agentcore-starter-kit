import {
  AgentCoreApplication,
  AgentCoreMcp,
  AgentCorePaymentManager,
  AgentCorePaymentConnector,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
  type CustomJWTAuthorizerConfig,
  type HarnessDeploymentConfig,
} from '@aws/agentcore-cdk';
import { CfnOutput, Stack, type StackProps } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

import { KitApi } from './kit-api';
import { KitKnowledgeBase } from './kit-knowledge-base';

/**
 * Harness deployment config: role-scoped fields (for IAM role + container build)
 * plus the full validated spec + its config directory so the L3 construct can
 * synthesize the AWS::BedrockAgentCore::Harness resource.
 */
export type HarnessConfig = HarnessDeploymentConfig;

export interface ManualPaymentConnectorSpec {
  name: string;
  provider: 'CoinbaseCDP' | 'StripePrivy';
  provisionMode?: 'MANUAL';
  credentialName: string;
  credentialProviderArn: string;
}

export interface QuickCreatePaymentConnectorSpec {
  name: string;
  provider: 'CoinbaseCDP';
  provisionMode: 'QUICK_CREATE';
  credentialName?: never;
  credentialProviderArn?: never;
}

export type PaymentConnectorSpec = ManualPaymentConnectorSpec | QuickCreatePaymentConnectorSpec;

export interface PaymentSpec {
  name: string;
  description?: string;
  authorizerType: 'AWS_IAM' | 'CUSTOM_JWT';
  authorizerConfiguration?: { customJWTAuthorizer: CustomJWTAuthorizerConfig };
  autoPayment?: boolean;
  paymentToolAllowlist?: string[];
  networkPreferences?: string[];
  connectors: PaymentConnectorSpec[];
}

export interface AgentCoreStackProps extends StackProps {
  /**
   * The AgentCore project specification containing agents, memories, and credentials.
   */
  spec: AgentCoreProjectSpec;
  /**
   * The MCP specification containing gateways and servers.
   */
  mcpSpec?: AgentCoreMcpSpec;
  /**
   * Credential provider ARNs from deployed state, keyed by credential name.
   */
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
  /**
   * Harness role configurations.
   */
  harnesses?: HarnessConfig[];
  /**
   * Parsed connectorParameters for non-S3 KB data sources, keyed by
   * connectorConfigFile path. Forwarded to AgentCoreApplication.
   */
  connectorParametersByFile?: Record<string, Record<string, unknown>>;
  /**
   * Payment specifications with resolved credential provider ARNs.
   */
  paymentSpec?: PaymentSpec[];
}

function toCdkId(name: string): string {
  return name.replace(/_/g, '');
}

/**
 * Decide whether a deployed runtime should receive payment env vars + IAM grants.
 * Payments today only ships a runtime shim for Python HTTP runtimes; injecting
 * AGENTCORE_PAYMENT_* env vars into TypeScript / MCP / A2A / AGUI runtimes
 * would surface env vars they cannot consume and would dilute least-privilege
 * IAM grants for runtimes that never call ProcessPayment.
 */
function isPaymentEligibleAgent(agent: { entrypoint?: string; protocol?: string }): boolean {
  if (agent.protocol && agent.protocol !== 'HTTP') {
    return false;
  }
  const entrypoint = typeof agent.entrypoint === 'string' ? agent.entrypoint : '';
  const entrypointFile = entrypoint.split(':')[0] ?? '';
  return entrypointFile.endsWith('.py');
}

/**
 * CDK Stack that deploys AgentCore infrastructure.
 *
 * This is a thin wrapper that instantiates L3 constructs.
 * All resource logic and outputs are contained within the L3 constructs.
 */
export class AgentCoreStack extends Stack {
  /** The AgentCore application containing all agent environments */
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials, harnesses, connectorParametersByFile, paymentSpec } = props;

    // Create AgentCoreApplication with all agents and harness roles
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const appProps: Record<string, unknown> = { spec };
    if (harnesses?.length) {
      appProps.harnesses = harnesses;
    }
    if (connectorParametersByFile && Object.keys(connectorParametersByFile).length > 0) {
      appProps.connectorParametersByFile = connectorParametersByFile;
    }
    if (credentials) {
      appProps.credentials = credentials;
    }
    this.application = new AgentCoreApplication(this, 'Application', appProps as any);

    // Create AgentCoreMcp if there are gateways configured
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });
    }

    // Create payment infrastructure via CFN constructs
    if (paymentSpec && paymentSpec.length > 0) {
      for (const payment of paymentSpec) {
        const mgrId = toCdkId(payment.name);
        const manager = new AgentCorePaymentManager(this, `Payment${mgrId}`, {
          projectName: spec.name,
          name: payment.name,
          authorizerType: payment.authorizerType,
          description: payment.description,
          authorizerConfiguration: payment.authorizerConfiguration,
          tags: spec.tags,
        });

        const prefix = `AGENTCORE_PAYMENT_${payment.name.toUpperCase().replace(/-/g, '_')}`;

        // Wire env vars from construct output tokens into eligible agent environments only.
        // See isPaymentEligibleAgent — non-Python or non-HTTP runtimes have no shim that
        // can consume these env vars, and giving them sts:AssumeRole on the
        // ProcessPaymentRole would broaden the privilege surface unnecessarily.
        for (const env of this.application.environments.values()) {
          if (!isPaymentEligibleAgent(env.agent)) {
            continue;
          }
          env.runtime.addEnvironmentVariable(`${prefix}_MANAGER_ARN`, manager.paymentManagerArn);
          env.runtime.addEnvironmentVariable(`${prefix}_PROCESS_PAYMENT_ROLE_ARN`, manager.processPaymentRoleArn);

          // Grant runtime execution role permission to assume the ProcessPaymentRole.
          // The ProcessPaymentRole's trust policy allows AccountRootPrincipal, but the
          // caller still needs sts:AssumeRole on its own role to perform the assumption.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: ['sts:AssumeRole'],
              resources: [manager.processPaymentRoleArn],
            })
          );

          // Grant payment data-plane actions directly to the runtime role.
          //
          // NOTE: This deviates from the canonical role model in the AgentCore Payments
          // beta guide, which assigns Get/List/Create instrument+session actions to a
          // separate ManagementRole and limits the agent's role to ProcessPayment only.
          // The current SDK plugin (AgentCorePaymentsPlugin.generate_payment_header)
          // calls GetPaymentInstrument internally during the 402 auto-pay path, so the
          // runtime role needs read access. CreatePaymentSession is included so
          // `agentcore invoke --auto-session` works without a separate ManagementRole
          // call. Tighten this if the SDK is updated to accept pre-fetched instrument
          // details and split create-session into a backend-only flow.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: [
                'bedrock-agentcore:GetPaymentInstrument',
                'bedrock-agentcore:ListPaymentInstruments',
                'bedrock-agentcore:GetPaymentInstrumentBalance',
                'bedrock-agentcore:GetPaymentSession',
                'bedrock-agentcore:ListPaymentSessions',
                'bedrock-agentcore:CreatePaymentSession',
                'bedrock-agentcore:ProcessPayment',
              ],
              resources: [manager.paymentManagerArn, `${manager.paymentManagerArn}/*`],
            })
          );

          if (payment.autoPayment !== undefined) {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTO_PAYMENT`, String(payment.autoPayment));
          }
          if (payment.paymentToolAllowlist) {
            env.runtime.addEnvironmentVariable(`${prefix}_TOOL_ALLOWLIST`, payment.paymentToolAllowlist.join(','));
          }
          if (payment.networkPreferences) {
            env.runtime.addEnvironmentVariable(`${prefix}_NETWORK_PREFERENCES`, payment.networkPreferences.join(','));
          }
          if (payment.authorizerType === 'CUSTOM_JWT') {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTH_MODE`, 'bearer');
          }
        }

        // Create connectors for this manager
        for (const connector of payment.connectors) {
          const connId = toCdkId(connector.name);
          const schemaConnector =
            connector.provisionMode === 'QUICK_CREATE'
              ? connector
              : {
                  name: connector.name,
                  provider: connector.provider,
                  ...(connector.provisionMode && { provisionMode: connector.provisionMode }),
                  credentialName: connector.credentialName,
                };
          const compatibilityProps = {
            projectName: spec.name,
            paymentManager: manager,
            connector: schemaConnector,
            // Remove these legacy manual fields after the new L3 release is pinned.
            connectorName: connector.name,
            connectorType: connector.provider,
            ...(connector.provisionMode !== 'QUICK_CREATE' && {
              credentialProviderArn: connector.credentialProviderArn,
            }),
          };
          const conn = new AgentCorePaymentConnector(
            this,
            `Payment${mgrId}${connId}`,
            compatibilityProps as unknown as ConstructorParameters<typeof AgentCorePaymentConnector>[2]
          );

          // Wire first connector's ID as env var (eligible agents only)
          if (connector === payment.connectors[0]) {
            for (const env of this.application.environments.values()) {
              if (!isPaymentEligibleAgent(env.agent)) continue;
              env.runtime.addEnvironmentVariable(`${prefix}_CONNECTOR_ID`, conn.paymentConnectorId);
            }
          }

          new CfnOutput(this, `Payment${mgrId}${connId}ConnectorId`, {
            value: conn.paymentConnectorId,
          });
          if (connector.provisionMode === 'QUICK_CREATE') {
            const quickCreateConnector = conn as AgentCorePaymentConnector & {
              paymentConnectorStatus: string;
              authorizationUrl: string;
            };
            new CfnOutput(this, `Payment${mgrId}${connId}ConnectorStatus`, {
              value: quickCreateConnector.paymentConnectorStatus,
            });
            new CfnOutput(this, `Payment${mgrId}${connId}AuthorizationUrl`, {
              value: quickCreateConnector.authorizationUrl,
            });
          }
        }

        // CFN Outputs for post-deploy state parsing
        new CfnOutput(this, `Payment${mgrId}ManagerArn`, {
          value: manager.paymentManagerArn,
        });
        new CfnOutput(this, `Payment${mgrId}ManagerId`, {
          value: manager.paymentManagerId,
        });
        new CfnOutput(this, `Payment${mgrId}ProcessPaymentRoleArn`, {
          value: manager.processPaymentRoleArn,
        });
        new CfnOutput(this, `Payment${mgrId}ResourceRetrievalRoleArn`, {
          value: manager.resourceRetrievalRoleArn,
        });
      }
    }

    // ── Kit: Bedrock Guardrails (not part of the agentcore.json schema, so
    // defined here alongside the L3 construct; the runtime discovers it via
    // env vars, mirroring how memories are wired). Sensible defaults on:
    // content filters plus prompt-attack detection. PROMPT_ATTACK output
    // strength must be NONE per the Bedrock API contract.
    const guardrail = new bedrock.CfnGuardrail(this, 'KitGuardrail', {
      name: `${spec.name}-guardrail`,
      description: 'Kit default guardrail: content filters and prompt-attack detection',
      blockedInputMessaging:
        'Sorry, I can’t help with that request. If you think this was blocked in error, the guardrail configuration is adjustable — see the Kit documentation.',
      blockedOutputsMessaging:
        'Sorry, I can’t provide that response. If you think this was blocked in error, the guardrail configuration is adjustable — see the Kit documentation.',
      contentPolicyConfig: {
        filtersConfig: [
          { type: 'SEXUAL', inputStrength: 'HIGH', outputStrength: 'HIGH' },
          { type: 'VIOLENCE', inputStrength: 'HIGH', outputStrength: 'HIGH' },
          { type: 'HATE', inputStrength: 'HIGH', outputStrength: 'HIGH' },
          { type: 'INSULTS', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
          { type: 'MISCONDUCT', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
          // LOW: blocks only HIGH-confidence attacks. Verified against the
          // classifier: instruction-override attacks ("ignore all previous
          // instructions...") score HIGH confidence and still block, while
          // benign first-contact phrasing ("introduce yourself in one line,
          // then tell me...") scores MEDIUM and must pass — at MEDIUM or
          // HIGH strength the agent blocks ordinary users on first contact.
          { type: 'PROMPT_ATTACK', inputStrength: 'LOW', outputStrength: 'NONE' },
        ],
      },
    });
    // CfnGuardrailVersion is immutable: editing the guardrail only updates its
    // DRAFT. Bump this description whenever the filters change — the
    // replacement snapshots the draft into a new numbered version.
    const guardrailVersion = new bedrock.CfnGuardrailVersion(this, 'KitGuardrailVersion', {
      guardrailIdentifier: guardrail.attrGuardrailId,
      description: 'Kit guardrail: content filters HIGH/MEDIUM, prompt-attack LOW (high-confidence only)',
    });
    for (const env of this.application.environments.values()) {
      env.runtime.addEnvironmentVariable('KIT_GUARDRAIL_ID', guardrail.attrGuardrailId);
      env.runtime.addEnvironmentVariable('KIT_GUARDRAIL_VERSION', guardrailVersion.attrVersion);
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:ApplyGuardrail'],
          resources: [guardrail.attrGuardrailArn],
        })
      );
    }
    new CfnOutput(this, 'KitGuardrailIdOutput', { value: guardrail.attrGuardrailId });

    // ── Kit: programmatic access (API Gateway + Lambda, API-key auth).
    const kitRuntime = this.application.environments.get('kit');
    if (kitRuntime) {
      new KitApi(this, 'KitApi', { runtimeArn: kitRuntime.runtime.runtimeArn });
    }

    // ── Kit: working knowledge base with sample corpus (S3 Vectors backed).
    const knowledgeBase = new KitKnowledgeBase(this, 'KitKb');
    if (kitRuntime) {
      kitRuntime.runtime.addEnvironmentVariable('KNOWLEDGE_BASE_ID', knowledgeBase.knowledgeBaseId);
      kitRuntime.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:Retrieve'],
          resources: [knowledgeBase.knowledgeBaseArn],
        })
      );
    }

    // Stack-level output
    new CfnOutput(this, 'StackNameOutput', {
      description: 'Name of the CloudFormation Stack',
      value: this.stackName,
    });
  }
}
