import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def analyze_security_compliance(topology: Dict[str, Any]) -> Dict[str, Any]:
    elements = topology.get("elements", [])
    if not elements:
        if isinstance(topology, list):
            elements = topology
            
    score = 100
    findings = []
    
    for element in elements:
        res_type = element.get('type', '').lower()
        res_name = element.get('name', 'Unknown Resource')
        config = element.get('config', {})
        
        # Check databases
        if 'db' in res_type or 'database' in res_type or 'sql' in res_type or 'postgres' in res_type:
            # Check public access
            public_access = config.get('public_network_access_enabled', False)
            if public_access or str(public_access).lower() == 'true':
                findings.append({
                    "severity": "High",
                    "resource": res_name,
                    "issue": "Database has public network access enabled.",
                    "remediation": "Disable public access and use Private Endpoints or VNet Service Endpoints."
                })
                score -= 15
                
            # Check encryption
            encryption = config.get('encryption_enabled', True)
            if not encryption or str(encryption).lower() == 'false':
                findings.append({
                    "severity": "High",
                    "resource": res_name,
                    "issue": "Database encryption at rest is disabled.",
                    "remediation": "Enable TDE (Transparent Data Encryption) or specify a customer-managed key."
                })
                score -= 15
                
        # Check storage
        if 'storage' in res_type:
            public_access = config.get('allow_blob_public_access', False)
            if public_access or str(public_access).lower() == 'true':
                findings.append({
                    "severity": "Medium",
                    "resource": res_name,
                    "issue": "Storage Account has public blob access allowed.",
                    "remediation": "Disable public access on the storage account unless explicitly required for public static assets."
                })
                score -= 10
                
            https_only = config.get('enable_https_traffic_only', True)
            if not https_only or str(https_only).lower() == 'false':
                findings.append({
                    "severity": "Medium",
                    "resource": res_name,
                    "issue": "Storage Account allows non-HTTPS traffic.",
                    "remediation": "Enable 'HTTPS traffic only' on the storage account."
                })
                score -= 10
                
        # Check VMs
        if 'vm' in res_type or 'machine' in res_type or 'compute' in res_type:
            ports = config.get('open_ports', [])
            if isinstance(ports, str):
                ports = [p.strip() for p in ports.split(',')]
                
            if '22' in ports or 22 in ports:
                findings.append({
                    "severity": "High",
                    "resource": res_name,
                    "issue": "SSH (port 22) is open to the internet.",
                    "remediation": "Close port 22 and use Azure Bastion or VPN for remote access."
                })
                score -= 15

            if '3389' in ports or 3389 in ports:
                findings.append({
                    "severity": "High",
                    "resource": res_name,
                    "issue": "RDP (port 3389) is open to the internet.",
                    "remediation": "Close port 3389 and use Azure Bastion or VPN for remote access."
                })
                score -= 15

    if score < 0:
        score = 0
        
    status = "Pass"
    if score < 80:
        status = "Warning"
    if score < 60:
        status = "Fail"
        
    return {
        "status": status,
        "score": score,
        "findings": findings,
        "summary": f"Security scan completed with a score of {score}/100. Found {len(findings)} issues."
    }
