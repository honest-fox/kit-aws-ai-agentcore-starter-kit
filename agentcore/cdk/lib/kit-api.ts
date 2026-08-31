import { CfnOutput, Duration } from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import * as fs from 'fs';
import * as path from 'path';

// Works from both lib/ (source) and dist/lib/ (compiled) layouts.
function findApiAssetPath(): string {
  const candidates = [
    path.join(__dirname, '../../../app/api'),
    path.join(__dirname, '../../../../app/api'),
  ];
  const found = candidates.find((p) => fs.existsSync(p));
  if (!found) {
    throw new Error(`Kit API Lambda source not found; tried: ${candidates.join(', ')}`);
  }
  return found;
}

export interface KitApiProps {
  /** ARN of the AgentCore runtime the API invokes. */
  runtimeArn: string;
}

/**
 * Kit programmatic access layer: REST API -> Lambda -> InvokeAgentRuntime.
 *
 * Authenticated by default: requests require an API key (x-api-key header),
 * and a usage plan throttles traffic so a leaked key cannot run up an
 * unbounded Bedrock bill. There is no unauthenticated route.
 */
export class KitApi extends Construct {
  constructor(scope: Construct, id: string, props: KitApiProps) {
    super(scope, id);

    const invokeFn = new lambda.Function(this, 'InvokeFunction', {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(findApiAssetPath()),
      timeout: Duration.seconds(120),
      memorySize: 256,
      environment: {
        KIT_RUNTIME_ARN: props.runtimeArn,
      },
      description: 'Kit: bridges API Gateway requests to the AgentCore runtime',
    });

    // InvokeAgentRuntime on this runtime (and its endpoints) only.
    invokeFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [props.runtimeArn, `${props.runtimeArn}/*`],
      })
    );

    const api = new apigateway.RestApi(this, 'RestApi', {
      restApiName: 'kit-api',
      description: 'Kit agent programmatic access',
      deployOptions: {
        stageName: 'v1',
        throttlingRateLimit: 5,
        throttlingBurstLimit: 10,
      },
    });

    const invoke = api.root.addResource('invoke');
    invoke.addMethod('POST', new apigateway.LambdaIntegration(invokeFn), {
      apiKeyRequired: true,
    });

    const apiKey = api.addApiKey('KitApiKey', { description: 'Kit default API key' });
    const plan = api.addUsagePlan('KitUsagePlan', {
      name: 'kit-default',
      throttle: { rateLimit: 5, burstLimit: 10 },
    });
    plan.addApiKey(apiKey);
    plan.addApiStage({ stage: api.deploymentStage });

    new CfnOutput(this, 'KitApiUrlOutput', {
      value: `${api.url}invoke`,
      description: 'Kit API endpoint (POST, x-api-key required)',
    });
    new CfnOutput(this, 'KitApiKeyIdOutput', {
      value: apiKey.keyId,
      description: 'API key id — fetch the value with: aws apigateway get-api-key --include-value --api-key <id>',
    });
  }
}
