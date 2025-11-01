#!/usr/bin/env python3
"""
create_account.py

- Importable function: create_member_account(...)
- CLI mode for testing: python3 create_account.py ...
- Uses role temp creds + OU lookup + account creation + move
"""

import json
import time
import sys
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

# ----------------------------------------------------------------------
# Import the helper that gives us temp role credentials
# ----------------------------------------------------------------------
from credential_and_role import setup_org_and_get_creds


# ----------------------------------------------------------------------
# 1. Resolve OU ID (shared helper)
# ----------------------------------------------------------------------
def resolve_ou_id(org_client, *, ou_name: str = None, ou_id: str = None) -> str:
    """
    Return the OU ID.
    - If ou_id → return it directly
    - If ou_name → search under root
    - Else → raise clear error
    """
    if ou_id:
        return ou_id

    if not ou_name:
        raise ValueError("Either ou_name or ou_id must be provided")

    root_id = org_client.list_roots()["Roots"][0]["Id"]
    paginator = org_client.get_paginator("list_organizational_units_for_parent")

    for page in paginator.paginate(ParentId=root_id):
        for ou in page.get("OrganizationalUnits", []):
            if ou["Name"] == ou_name:
                return ou["Id"]

    raise ValueError(f"OU named '{ou_name}' not found under the root.")


# ----------------------------------------------------------------------
# 2. Main function – importable!
# ----------------------------------------------------------------------
def create_member_account(
    account_name: str,
    account_email: str,
    ou: str,                     # ← can be OU name OR OU ID
    role_name: str = "OrgAdminRole",
    *,
    _debug: bool = False
) -> Dict[str, Any]:
    
    if not account_name or not account_email or not ou:
        raise ValueError("account_name, account_email, and ou are required")

    # 1. Get temp role credentials
    creds = setup_org_and_get_creds(role_name)
    if _debug:
        print(f"Assuming role: {creds['role_arn']}")

    session = boto3.Session(
        aws_access_key_id=creds["access_key_id"],
        aws_secret_access_key=creds["secret_access_key"],
        aws_session_token=creds["session_token"],
        region_name="us-east-1",
    )
    org_client = session.client("organizations")

    # 2. Resolve OU – auto-detect if it's ID or name
    try:
        # Try as ID first (starts with "ou-")
        if ou.startswith("ou-") and len(ou) > 10:
            target_ou_id = ou
            if _debug:
                print(f"Using OU ID: {target_ou_id}")
        else:
            target_ou_id = resolve_ou_id(org_client, ou_name=ou)
            if _debug:
                print(f"Resolved OU name '{ou}' → ID: {target_ou_id}")
    except Exception as e:
        raise ValueError(f"Cannot resolve OU '{ou}': {e}")

    # 3. Start account creation
    try:
        resp = org_client.create_account(
            Email=account_email,
            AccountName=account_name,
            RoleName=role_name,
            IamUserAccessToBilling="ALLOW",
        )
        create_id = resp["CreateAccountStatus"]["Id"]
        if _debug:
            print(f"Creation started: {create_id}")
    except ClientError as e:
        if "Finalizing" in str(e):
            create_id = str(e).split()[-1]
            if _debug:
                print(f"Creation already in progress: {create_id}")
        else:
            raise

    # 4. Wait for completion
    if _debug:
        print("Waiting for account to be ready...")
    while True:
        status = org_client.describe_create_account_status(CreateAccountRequestId=create_id)
        state = status["CreateAccountStatus"]["State"]
        if _debug:
            print(f"   → {state}", end="")
        if state == "SUCCEEDED":
            account_id = status["CreateAccountStatus"]["AccountId"]
            if _debug:
                print(f" → Account ID: {account_id}")
            break
        if state == "FAILED":
            reason = status["CreateAccountStatus"].get("FailureReason", "Unknown")
            raise RuntimeError(f"Account creation failed: {reason}")
        if _debug:
            print()
        time.sleep(6)

    # 5. Move to OU
    root_id = org_client.list_roots()["Roots"][0]["Id"]
    if _debug:
        print(f"Moving {account_id} → OU {target_ou_id}")
    org_client.move_account(
        AccountId=account_id,
        SourceParentId=root_id,
        DestinationParentId=target_ou_id,
    )

    # 6. Return result
    result = creds.copy()
    result.update({
        "account_name": account_name,
        "account_id": account_id,
        "account_email": account_email,
        "ou_id": target_ou_id,
        "create_request_id": create_id,
    })
    return result


# ----------------------------------------------------------------------
# 3. CLI MODE – for testing
# ----------------------------------------------------------------------
if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description="Create an AWS member account inside an existing OU"
    )
    parser.add_argument("account_name", help="Name of the new account")
    parser.add_argument("account_email", help="Unique email for the new account")
    parser.add_argument("ou", help="OU name OR OU ID (e.g. 'Development' or 'ou-abcd-12345678')")
    parser.add_argument("--role", default="OrgAdminRole", help="IAM role name (default: OrgAdminRole)")

    args = parser.parse_args()

    try:
        result = create_member_account(
            account_name=args.account_name,
            account_email=args.account_email,
            ou=args.ou,
            role_name=args.role,
            _debug=True  # show progress
        )
        print("\nSUCCESS! Account created and moved to OU.\n")
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)