#!/usr/bin/env python3
"""
Flask API: /get-aws-creds
Returns temporary AWS credentials for Organizations API
Safe to call anytime — creates org/role if missing
"""

from flask import Flask, request, jsonify
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import sys
from datetime import datetime

app = Flask(__name__)

# ------------------------------------------------------------------
# 1. AWS Clients (shared)
# ------------------------------------------------------------------
def get_client(service, region=None):
    config = Config(
        region_name=region or 'us-east-1',
        retries={'max_attempts': 10, 'mode': 'standard'},
        read_timeout=30,
        connect_timeout=30
    )
    return boto3.client(service, config=config)

# ------------------------------------------------------------------
# 2. Core Logic (same as before, but silent)
# ------------------------------------------------------------------
def setup_org_and_get_creds(role_name: str) -> dict:
    if not role_name or not isinstance(role_name, str):
        raise ValueError("role_name is required")

    sts_client = get_client('sts')
    org_client = get_client('organizations', 'us-east-1')
    iam_client = get_client('iam')

    # 1. Get account ID
    account_id = sts_client.get_caller_identity()['Account']

    # 2. Ensure org exists
    try:
        org_id = org_client.describe_organization()['Organization']['Id']
    except org_client.exceptions.AWSOrganizationsNotInUseException:
        resp = org_client.create_organization(FeatureSet='ALL')
        org_id = resp['Organization']['Id']
    except ClientError as e:
        if e.response['Error']['Code'] == 'AccessDeniedException':
            raise PermissionError("ROOT user required to create organization")
        raise

    # 3. Create or reuse role
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole"
        }]
    }

    try:
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Auto-created for mobile app"
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

    # 4. Assume role → fresh creds
    resp = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName="mobile-app-session",
        DurationSeconds=3600
    )
    creds = resp['Credentials']

    # 5. Return dict
    return {
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

# ------------------------------------------------------------------
# 3. API Endpoint
# ------------------------------------------------------------------
@app.route('/get-aws-creds', methods=['GET', 'POST'])
def get_aws_creds():
    try:
        # Get role_name from query, JSON, or default
        if request.is_json:
            data = request.get_json()
            role_name = data.get('role_name')
        else:
            role_name = request.args.get('role_name')

        if not role_name:
            return jsonify({"error": "role_name is required"}), 400

        creds = setup_org_and_get_creds(role_name)
        return jsonify(creds)

    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# ------------------------------------------------------------------
# 4. Health Check
# ------------------------------------------------------------------
@app.route('/health')
def health():
    return jsonify({"status": "ok"})

# ------------------------------------------------------------------
# 5. Run
# ------------------------------------------------------------------
if __name__ == '__main__':
    # Use environment variables for root credentials
    app.run(host='0.0.0.0', port=5000, debug=False)