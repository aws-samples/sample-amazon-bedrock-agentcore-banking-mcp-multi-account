from aws_cdk import (
    Stack, CfnOutput, RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_ecr_assets as ecr_assets,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
)
from constructs import Construct
import os


class WebAppStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 ecs_exec_role_arn: str, ecs_task_role_arn: str,
                 okta_issuer: str, okta_spa_client_id: str,
                 okta_web_client_id: str = "", okta_web_client_secret: str = "",
                 **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        prefix = self.node.try_get_context("project_prefix") or "LOBFederation"
        prefix_lower = prefix.lower().replace(" ", "-")
        project_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")

        exec_role = iam.Role.from_role_arn(self, "ExecRole", ecs_exec_role_arn, mutable=False)
        task_role = iam.Role.from_role_arn(self, "TaskRole", ecs_task_role_arn, mutable=False)

        # --- VPC (default) ---
        vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)

        # --- ECS Cluster ---
        cluster = ecs.Cluster(self, "Cluster",
            cluster_name=f"{prefix_lower}-cluster", vpc=vpc)

        # --- Log Group ---
        log_group = logs.LogGroup(self, "LogGroup",
            log_group_name=f"/ecs/{prefix_lower}",
            removal_policy=RemovalPolicy.DESTROY)

        # --- Docker Image Assets ---
        frontend_image = ecr_assets.DockerImageAsset(self, "FrontendImage",
            directory=os.path.join(project_dir, "platform-account", "webapp", "frontend"),
            build_args={
                "REACT_APP_OKTA_ISSUER": okta_issuer,
                "REACT_APP_OKTA_CLIENT_ID": okta_spa_client_id,
            },
        )
        backend_image = ecr_assets.DockerImageAsset(self, "BackendImage",
            directory=os.path.join(project_dir, "platform-account", "webapp", "backend"),
        )

        # --- Task Definition ---
        task_def = ecs.FargateTaskDefinition(self, "TaskDef",
            cpu=1024, memory_limit_mib=3072,
            execution_role=exec_role, task_role=task_role)

        task_def.add_container("frontend",
            image=ecs.ContainerImage.from_docker_image_asset(frontend_image),
            essential=True,
            port_mappings=[ecs.PortMapping(container_port=80)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="frontend", log_group=log_group),
        )

        task_def.add_container("backend",
            image=ecs.ContainerImage.from_docker_image_asset(backend_image),
            essential=True,
            port_mappings=[ecs.PortMapping(container_port=8000)],
            environment={
                "AGENT_RUNTIME_ARN": self.node.try_get_context("agent_runtime_arn") or "PLACEHOLDER",
                "OKTA_ISSUER": okta_issuer,
                "OKTA_CLIENT_ID": okta_web_client_id or okta_spa_client_id,
                "OKTA_CLIENT_SECRET": okta_web_client_secret,
                "GUARDRAIL_ID": self.node.try_get_context("guardrail_id") or "",
                "GUARDRAIL_VERSION": self.node.try_get_context("guardrail_version") or "1",
                "FRONTEND_URL": self.node.try_get_context("frontend_url") or "",
                "BACKEND_URL": self.node.try_get_context("backend_url") or "",
                "AWS_DEFAULT_REGION": self.region,
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="backend", log_group=log_group),
        )

        # --- ALB ---
        self.alb = elbv2.ApplicationLoadBalancer(self, "ALB",
            load_balancer_name=f"{prefix_lower}-alb",
            vpc=vpc, internet_facing=True)

        listener = self.alb.add_listener("HttpListener", port=80, open=False)

        # Restrict ALB to CloudFront-only traffic
        cf_prefix_list = ec2.PrefixList.from_lookup(self, "CfPrefixList",
            prefix_list_name="com.amazonaws.global.cloudfront.origin-facing")
        self.alb.connections.security_groups[0].add_ingress_rule(
            ec2.Peer.prefix_list(cf_prefix_list.prefix_list_id),
            ec2.Port.tcp(80), "CloudFront origin-facing only")

        ecs_sg = ec2.SecurityGroup(self, "EcsSG", vpc=vpc,
            description="ECS tasks SG", allow_all_outbound=True)
        ecs_sg.add_ingress_rule(self.alb.connections.security_groups[0],
            ec2.Port.tcp(80), "ALB to frontend")
        ecs_sg.add_ingress_rule(self.alb.connections.security_groups[0],
            ec2.Port.tcp(8000), "ALB to backend")

        service = ecs.FargateService(self, "Service",
            cluster=cluster, task_definition=task_def,
            desired_count=1, assign_public_ip=True,
            security_groups=[ecs_sg])

        listener.add_targets("FrontendTG",
            port=80, protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service.load_balancer_target(container_name="frontend", container_port=80)],
            health_check=elbv2.HealthCheck(path="/"))

        listener.add_targets("BackendTG",
            port=8000, protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service.load_balancer_target(container_name="backend", container_port=8000)],
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*"])],
            priority=10,
            health_check=elbv2.HealthCheck(path="/api/health"))

        CfnOutput(self, "AlbDnsName", value=self.alb.load_balancer_dns_name)
        CfnOutput(self, "AlbUrl", value=f"http://{self.alb.load_balancer_dns_name}")
