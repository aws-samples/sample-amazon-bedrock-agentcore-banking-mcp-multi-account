from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput, CustomResource, Duration,
    aws_s3 as s3,
    aws_opensearchserverless as oss,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_lambda as _lambda,
    custom_resources as cr,
)
from constructs import Construct
import json

INDEX_NAME = "bedrock-knowledge-base-default-index"
VECTOR_FIELD = "bedrock-knowledge-base-default-vector"
TEXT_FIELD = "AMAZON_BEDROCK_TEXT_CHUNK"
METADATA_FIELD = "AMAZON_BEDROCK_METADATA"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
VECTOR_DIMENSION = 1024


class KnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        lob_name = self.node.try_get_context("lob_name") or "lending-wealth"
        prefix = lob_name  # e.g. "lending-wealth"

        # --- S3 Bucket for policy documents ---
        self.docs_bucket = s3.Bucket(
            self, "PolicyDocsBucket",
            bucket_name=f"{prefix}-policy-docs-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- OpenSearch Serverless policies ---
        collection_name = f"{prefix}-vectors"

        oss.CfnSecurityPolicy(
            self, "EncryptionPolicy",
            name=f"{prefix}-enc",
            type="encryption",
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]}],
                "AWSOwnedKey": True,
            }),
        )

        oss.CfnSecurityPolicy(
            self, "NetworkPolicy",
            name=f"{prefix}-net",
            type="network",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]},
                    {"ResourceType": "dashboard", "Resource": [f"collection/{collection_name}"]},
                ],
                "AllowFromPublic": True,
            }]),
        )

        # --- KB Execution Role ---
        self.kb_role = iam.Role(
            self, "KbExecutionRole",
            role_name=f"{prefix}-KbExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}}),
            inline_policies={
                "KbPolicy": iam.PolicyDocument(statements=[
                    iam.PolicyStatement(
                        actions=["s3:GetObject", "s3:ListBucket"],
                        resources=[self.docs_bucket.bucket_arn, f"{self.docs_bucket.bucket_arn}/*"],
                    ),
                    iam.PolicyStatement(
                        actions=["aoss:APIAccessAll"],
                        resources=[f"arn:aws:aoss:{self.region}:{self.account}:collection/*"],
                    ),
                    iam.PolicyStatement(
                        actions=["bedrock:InvokeModel"],
                        resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}"],
                    ),
                ])
            },
        )

        # --- Data Access Policy ---
        cfn_exec_role = f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-cfn-exec-role-{self.account}-{self.region}"
        data_access_policy = oss.CfnAccessPolicy(
            self, "DataAccessPolicy",
            name=f"{prefix}-access",
            type="data",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection", "Resource": [f"collection/{collection_name}"],
                     "Permission": ["aoss:CreateCollectionItems", "aoss:UpdateCollectionItems",
                                    "aoss:DescribeCollectionItems"]},
                    {"ResourceType": "index", "Resource": [f"index/{collection_name}/*"],
                     "Permission": ["aoss:CreateIndex", "aoss:DeleteIndex", "aoss:UpdateIndex", "aoss:DescribeIndex",
                                    "aoss:ReadDocument", "aoss:WriteDocument"]},
                ],
                "Principal": [self.kb_role.role_arn, cfn_exec_role, f"arn:aws:iam::{self.account}:root"],
            }]),
        )

        # --- Collection ---
        self.collection = oss.CfnCollection(
            self, "VectorCollection",
            name=collection_name,
            type="VECTORSEARCH",
        )
        self.collection.node.add_dependency(self.node.find_child("EncryptionPolicy"))
        self.collection.node.add_dependency(self.node.find_child("NetworkPolicy"))

        # --- Vector Index ---
        vector_index = oss.CfnIndex(
            self, "VectorIndex",
            collection_endpoint=self.collection.attr_collection_endpoint,
            index_name=INDEX_NAME,
            settings=oss.CfnIndex.IndexSettingsProperty(
                index=oss.CfnIndex.IndexProperty(knn=True),
            ),
            mappings=oss.CfnIndex.MappingsProperty(
                properties={
                    VECTOR_FIELD: oss.CfnIndex.PropertyMappingProperty(
                        type="knn_vector", dimension=VECTOR_DIMENSION,
                        method=oss.CfnIndex.MethodProperty(engine="faiss", name="hnsw"),
                    ),
                    TEXT_FIELD: oss.CfnIndex.PropertyMappingProperty(type="text"),
                    METADATA_FIELD: oss.CfnIndex.PropertyMappingProperty(type="text"),
                },
            ),
        )
        vector_index.node.add_dependency(data_access_policy)

        # --- Wait for AOSS access policy propagation ---
        access_wait_fn = _lambda.Function(
            self, "AccessPolicyWaitFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(60),
            code=_lambda.Code.from_inline(
                "import cfnresponse, time\n"
                "def handler(event, context):\n"
                "    if event['RequestType'] in ('Create', 'Update'):\n"
                "        time.sleep(30)\n"
                "    cfnresponse.send(event, context, cfnresponse.SUCCESS, {})\n"
            ),
        )
        access_wait = CustomResource(self, "AccessPolicyWait", service_token=access_wait_fn.function_arn)
        access_wait.node.add_dependency(data_access_policy)
        access_wait.node.add_dependency(self.collection)
        vector_index.node.add_dependency(access_wait)

        # --- Wait for index ---
        wait_fn = _lambda.Function(
            self, "IndexWaitFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(90),
            code=_lambda.Code.from_inline(
                "import cfnresponse, time\n"
                "def handler(event, context):\n"
                "    if event['RequestType'] in ('Create', 'Update'):\n"
                "        time.sleep(60)\n"
                "    cfnresponse.send(event, context, cfnresponse.SUCCESS, {})\n"
            ),
        )
        index_wait = CustomResource(self, "IndexWait", service_token=wait_fn.function_arn)
        index_wait.node.add_dependency(vector_index)

        # --- Bedrock Knowledge Base ---
        self.kb = bedrock.CfnKnowledgeBase(
            self, "KnowledgeBase",
            name=f"{prefix}-knowledge-base",
            description=f"Banking policy documents for {lob_name}",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}",
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=self.collection.attr_arn,
                    vector_index_name=INDEX_NAME,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field=VECTOR_FIELD, text_field=TEXT_FIELD, metadata_field=METADATA_FIELD,
                    ),
                ),
            ),
        )
        self.kb.node.add_dependency(index_wait)

        # --- S3 Data Source ---
        self.data_source = bedrock.CfnDataSource(
            self, "S3DataSource",
            knowledge_base_id=self.kb.attr_knowledge_base_id,
            name=f"{prefix}-s3-datasource",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.docs_bucket.bucket_arn,
                ),
            ),
            data_deletion_policy="RETAIN",
        )

        # --- Trigger Ingestion ---
        self.ingestion_trigger = cr.AwsCustomResource(
            self, "IngestionTrigger",
            on_create=cr.AwsSdkCall(
                service="BedrockAgent", action="startIngestionJob",
                parameters={
                    "knowledgeBaseId": self.kb.attr_knowledge_base_id,
                    "dataSourceId": self.data_source.attr_data_source_id,
                },
                physical_resource_id=cr.PhysicalResourceId.of("IngestionTrigger"),
            ),
            on_update=cr.AwsSdkCall(
                service="BedrockAgent", action="startIngestionJob",
                parameters={
                    "knowledgeBaseId": self.kb.attr_knowledge_base_id,
                    "dataSourceId": self.data_source.attr_data_source_id,
                },
                physical_resource_id=cr.PhysicalResourceId.of("IngestionTrigger"),
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["bedrock:StartIngestionJob"],
                    resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"],
                ),
            ]),
        )

        # --- Outputs ---
        CfnOutput(self, "KnowledgeBaseId", value=self.kb.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=self.data_source.attr_data_source_id)
        CfnOutput(self, "DocsBucketName", value=self.docs_bucket.bucket_name)
        CfnOutput(self, "CollectionEndpoint", value=self.collection.attr_collection_endpoint)
