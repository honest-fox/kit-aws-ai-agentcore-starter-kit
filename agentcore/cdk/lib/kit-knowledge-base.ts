import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import * as fs from 'fs';
import * as path from 'path';

const EMBEDDING_MODEL_ID = 'amazon.titan-embed-text-v2:0';
const EMBEDDING_DIMENSION = 1024;

// Works from both lib/ (source) and dist/lib/ (compiled) layouts.
function findSampleDataPath(): string {
  const candidates = [
    path.join(__dirname, '../../../sample-data'),
    path.join(__dirname, '../../../../sample-data'),
  ];
  const found = candidates.find((p) => fs.existsSync(p));
  if (!found) {
    throw new Error(`Kit sample data not found; tried: ${candidates.join(', ')}`);
  }
  return found;
}

/**
 * Kit knowledge base: a working RAG setup out of the box.
 *
 * Everything here is GA AWS: a standard Bedrock Knowledge Base backed by
 * S3 Vectors (no OpenSearch Serverless minimum-OCU cost — the whole thing
 * costs cents), fed from an S3 corpus bucket seeded with Kit's sample
 * documents. Deleting the stack removes the buckets, vectors, and KB.
 *
 * Swap the sample corpus for your own data by replacing sample-data/ and
 * redeploying — see the extension guide.
 */
export class KitKnowledgeBase extends Construct {
  public readonly knowledgeBaseId: string;
  public readonly knowledgeBaseArn: string;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    const stack = Stack.of(this);

    const corpusBucket = new s3.Bucket(this, 'CorpusBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const corpusDeployment = new s3deploy.BucketDeployment(this, 'CorpusDeployment', {
      sources: [s3deploy.Source.asset(findSampleDataPath())],
      destinationBucket: corpusBucket,
    });

    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket');
    const vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketArn: vectorBucket.attrVectorBucketArn,
      indexName: 'kit-kb-index',
      dataType: 'float32',
      dimension: EMBEDDING_DIMENSION,
      distanceMetric: 'cosine',
      metadataConfiguration: {
        // Bedrock stores each chunk's text in metadata; it must be
        // non-filterable or ingestion fails on metadata size limits.
        nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT'],
      },
    });

    const kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': stack.account },
        },
      }),
      description: 'Kit: Bedrock Knowledge Base service role',
    });
    corpusBucket.grantRead(kbRole);
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          's3vectors:GetIndex',
          's3vectors:PutVectors',
          's3vectors:GetVectors',
          's3vectors:QueryVectors',
          's3vectors:DeleteVectors',
          's3vectors:ListVectors',
        ],
        resources: [vectorIndex.attrIndexArn],
      })
    );
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [
          `arn:${stack.partition}:bedrock:${stack.region}::foundation-model/${EMBEDDING_MODEL_ID}`,
        ],
      })
    );

    const knowledgeBase = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: 'kit-knowledge-base',
      description: 'Kit sample knowledge base — fictional Kookaburra Coffee Co. corpus',
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:${stack.partition}:bedrock:${stack.region}::foundation-model/${EMBEDDING_MODEL_ID}`,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: EMBEDDING_DIMENSION,
              embeddingDataType: 'FLOAT32',
            },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          indexArn: vectorIndex.attrIndexArn,
        },
      },
    });
    knowledgeBase.node.addDependency(kbRole);

    const dataSource = new bedrock.CfnDataSource(this, 'CorpusDataSource', {
      name: 'kit-sample-corpus',
      knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
      dataDeletionPolicy: 'RETAIN',
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: corpusBucket.bucketArn,
        },
      },
    });

    // Ingest the corpus on create and on every deploy so corpus updates
    // land without a manual sync step.
    const ingestion = new cr.AwsCustomResource(this, 'CorpusIngestion', {
      onUpdate: {
        service: 'bedrock-agent',
        action: 'StartIngestionJob',
        parameters: {
          knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
          dataSourceId: dataSource.attrDataSourceId,
          // clientToken must be >= 33 characters.
          clientToken: `kit-corpus-ingestion-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
        },
        physicalResourceId: cr.PhysicalResourceId.of('kit-corpus-ingestion'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['bedrock:StartIngestionJob'],
          resources: [knowledgeBase.attrKnowledgeBaseArn],
        }),
      ]),
      timeout: Duration.minutes(5),
    });
    ingestion.node.addDependency(corpusDeployment);
    ingestion.node.addDependency(dataSource);

    this.knowledgeBaseId = knowledgeBase.attrKnowledgeBaseId;
    this.knowledgeBaseArn = knowledgeBase.attrKnowledgeBaseArn;

    new CfnOutput(this, 'KitKnowledgeBaseIdOutput', { value: this.knowledgeBaseId });
  }
}
