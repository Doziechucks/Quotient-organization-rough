# create_ou.py
from credential_and_role import setup_org_and_get_creds
import boto3
from botocore.exceptions import ClientError
import json

def create_organizational_unit(ou_name: str, role_name: str = "OrgAdminRole") -> dict:
    """
    Creates an OU using credentials from setup_org_and_get_creds()

    Args:
        ou_name (str): Name of OU to create
        role_name (str): Role to use (must exist or will be created)

    Returns:
        dict: OU info + temp credentials
    """
    if not ou_name:
        raise ValueError("ou_name is required")

    # 1. Get temp credentials
    creds = setup_org_and_get_creds(role_name)

    # 2. Create session with temp creds
    session = boto3.Session(
        aws_access_key_id=creds['access_key_id'],
        aws_secret_access_key=creds['secret_access_key'],
        aws_session_token=creds['session_token'],
        region_name='us-east-1'
    )
    org_client = session.client('organizations')

    # 3. Get root parent
    roots = org_client.list_roots()['Roots']
    root_id = roots[0]['Id']

    # 4. Create OU
    try:
        response = org_client.create_organizational_unit(
            ParentId=root_id,
            Name=ou_name
        )
        ou = response['OrganizationalUnit']
        ou_id = ou['Id']
    except ClientError as e:
        if 'DuplicateOrganizationalUnitNameException' in str(e):
            # Reuse existing
            ous = org_client.list_organizational_units_for_parent(ParentId=root_id)['OrganizationalUnits']
            existing = next((ou for ou in ous if ou['Name'] == ou_name), None)
            ou_id = existing['Id'] if existing else None
        else:
            raise

    # 5. Return full result
    result = creds.copy()
    result.update({
        "ou_name": ou_name,
        "ou_id": ou_id
    })
    return result


# ——— CLI Example ———
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("ou_name", help="Name of OU")
    parser.add_argument("--role", default="OrgAdminRole", help="IAM role name")
    args = parser.parse_args()

    result = create_organizational_unit(args.ou_name, args.role)
    print(json.dumps(result, indent=2))