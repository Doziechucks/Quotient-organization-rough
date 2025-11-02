from credential_and_role import setup_org_and_get_creds
import boto3
from botocore.exceptions import ClientError
import json

def create_organizational_unit(
    ou_name: str,
    parent_ou_id: str = None,
    parent_ou_name: str = None,
    role_name: str = None
) -> dict:
    """
    Creates an OU under the root or under another OU using temp credentials.

    Args:
        ou_name (str): Name of the OU to create.
        parent_ou_id (str, optional): ID of the parent OU. Defaults to root if None.
        parent_ou_name (str, optional): Name of parent OU (used to build role if nested).
        role_name (str, optional): Name of role to use. If None, defaults based on parent.

    Returns:
        dict: Created OU info + credentials used.
    """
    if not ou_name:
        raise ValueError("ou_name is required")

    # 1. Determine role
    if parent_ou_id or parent_ou_name:
        # Nested OU → role is "<ParentOUName>AdminRole"
        role_name = role_name or f"{parent_ou_name}AdminRole"
    else:
        # Top-level OU → use management account role
        role_name = role_name or "OrgAdminRole"

    # 2. Get temp credentials for the role
    creds = setup_org_and_get_creds(role_name)

    # 3. Create session with temp creds
    session = boto3.Session(
        aws_access_key_id=creds['access_key_id'],
        aws_secret_access_key=creds['secret_access_key'],
        aws_session_token=creds['session_token'],
        region_name='us-east-1'
    )
    org_client = session.client('organizations')

    # 4. Determine parent ID
    if parent_ou_id:
        parent_id = parent_ou_id
    elif parent_ou_name:
    # look up the OU ID by name under the root
        roots = org_client.list_roots()['Roots']
        root_id = roots[0]['Id']
    # List all OUs under the root (or you could allow deeper nesting if needed)
        ous = org_client.list_organizational_units_for_parent(ParentId=root_id)['OrganizationalUnits']
        parent_ou = next((ou for ou in ous if ou['Name'] == parent_ou_name), None)
        if not parent_ou:
            raise ValueError(f"Parent OU named '{parent_ou_name}' not found under root")
        parent_id = parent_ou['Id']
    else:
    # default to root
        roots = org_client.list_roots()['Roots']
        parent_id = roots[0]['Id']


    # 5. Create OU
    try:
        response = org_client.create_organizational_unit(
            ParentId=parent_id,
            Name=ou_name
        )
        ou = response['OrganizationalUnit']
        ou_id = ou['Id']
    except ClientError as e:
        if 'DuplicateOrganizationalUnitNameException' in str(e):
            # Reuse existing
            ous = org_client.list_organizational_units_for_parent(ParentId=parent_id)['OrganizationalUnits']
            existing = next((ou for ou in ous if ou['Name'] == ou_name), None)
            ou_id = existing['Id'] if existing else None
        else:
            raise

    # 6. Return full result
    result = creds.copy()
    result.update({
        "ou_name": ou_name,
        "ou_id": ou_id,
        "parent_ou_id": parent_id
    })
    return result


# ——— CLI Example ———
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("ou_name", help="Name of OU to create")
    parser.add_argument("--parent-id", help="Parent OU ID (default: root)", default=None)
    parser.add_argument("--parent-name", help="Parent OU name (used to build role for nested OU)", default=None)
    parser.add_argument("--role", help="Role name to use (optional)", default=None)
    args = parser.parse_args()

    result = create_organizational_unit(
        ou_name=args.ou_name,
        parent_ou_id=args.parent_id,
        parent_ou_name=args.parent_name,
        role_name=args.role
    )

    print(json.dumps(result, indent=2))