#!/usr/bin/env python3


import sys
import json
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
# from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def get_client(service, region=None):
    config = Config(
        region_name=region or 'us-east-1',
        retries={'max_attempts': 10, 'mode': 'standard'},
        read_timeout=30,
        connect_timeout=30
    )
    return boto3.client(service, config=config)

def setup_org_and_get_creds(role_name: str) -> dict:
    """
    Creates org + IAM role + assumes it → returns temp credentials as dict.
    """
    if not role_name or not isinstance(role_name, str):
        raise ValueError("role_name must be a non-empty string")

    sts_client = get_client('sts')
    org_client = get_client('organizations', 'us-east-1')
    iam_client = get_client('iam')

    # 1. Get account ID
    account_id = sts_client.get_caller_identity()['Account']

    # 2. Ensure organization exists
    try:
        org = org_client.describe_organization()['Organization']
        org_id = org['Id']
    except org_client.exceptions.AWSOrganizationsNotInUseException:
        resp = org_client.create_organization(FeatureSet='ALL')
        org_id = resp['Organization']['Id']
    except ClientError as e:
        if e.response['Error']['Code'] == 'AccessDeniedException':
            raise PermissionError(
                "Access denied on DescribeOrganization. "
                "You must use credentials from the MANAGEMENT ACCOUNT "
                "that owns the AWS Organization."
            )

    # 3. Create or get IAM role
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": "arn:aws:iam::123456789012:user/org-admin-user"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    try:
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Auto-created for mobile app org management"
        )
    except ClientError as e:
        if e.response['Error']['Code'] != 'EntityAlreadyExists':
            raise

    # Attach policy
    policy_arn = 'arn:aws:iam::aws:policy/AWSOrganizationsFullAccess'
    try:
        iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    except ClientError:
        pass  # already attached

    # 4. Assume role → get temp creds
    resp = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName="mobile-app-session",
        DurationSeconds=3600
    )
    creds = resp['Credentials']

    # 5. Build result
    result = {
        "role_name": role_name,
        "role_arn": role_arn,
        "account_id": account_id,
        "organization_id": org_id,
        "access_key_id": creds['AccessKeyId'],
        "secret_access_key": creds['SecretAccessKey'],
        "session_token": creds['SessionToken'],
        "region": "us-east-1",
        "expires_at": creds['Expiration'].strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    return result


# ————————————————————————
# Example Usage
# ————————————————————————
if __name__ == "__main__":
    ROLE_NAME = "MobileOrgAdmin"  # ← Change this or pass via CLI/ENV

    try:
        creds = setup_org_and_get_creds(ROLE_NAME)
        # Pretty print only when run directly
        print(json.dumps(creds, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)