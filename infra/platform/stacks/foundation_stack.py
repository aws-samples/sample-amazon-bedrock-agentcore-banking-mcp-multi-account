from aws_cdk import (
    Stack, CfnOutput,
    aws_iam as iam,
)
from constructs import Construct


class FoundationStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        prefix = self.node.try_get_context("project_prefix") or "LOBFederation"
        prefix_lower = prefix.lower().replace(" ", "-")

        # --- Gateway Execution Role ---
        self.gateway_role = iam.Role(
            self, "GatewayExecutionRole",
            role_name=f"{prefix}-GatewayExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            inline_policies={
                "GatewayPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=["bedrock-agentcore:*"],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=["secretsmanager:GetSecretValue"],
                            resources=[
                                f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:{prefix_lower}/*",
                                f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:bedrock-agentcore*",
                            ],
                        ),
                    ]
                )
            },
        )

        # --- ECS Task Execution Role ---
        self.ecs_exec_role = iam.Role(
            self, "EcsTaskExecutionRole",
            role_name=f"{prefix}-EcsTaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy"),
            ],
        )

        # --- ECS Task Role ---
        self.ecs_task_role = iam.Role(
            self, "EcsTaskRole",
            role_name=f"{prefix}-EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            inline_policies={
                "EcsTaskPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                                "bedrock:ApplyGuardrail",
                            ],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "bedrock-agentcore:InvokeAgentRuntime",
                            ],
                            resources=["*"],
                        ),
                    ]
                )
            },
        )

        # --- Outputs ---
        CfnOutput(self, "GatewayRoleArn", value=self.gateway_role.role_arn)
        CfnOutput(self, "EcsTaskExecutionRoleArn", value=self.ecs_exec_role.role_arn)
        CfnOutput(self, "EcsTaskRoleArn", value=self.ecs_task_role.role_arn)
