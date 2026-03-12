
def fix_file(path, replacements):
    try:
        with open(path, "r") as f:
            content = f.read()
        for old, new in replacements:
            content = content.replace(old, new)
        with open(path, "w") as f:
            f.write(content)
        print(f"Fixed {path}")
    except Exception as e:
        print(f"Failed {path}: {e}")

fix_file("icons/builders/drawio.py", [
    ('logger.info("Returning cached draw.io library for %s", pack_id)',
     'logger.info("Returning cached draw.io library for %s", str(pack_id).replace("\\n", "").replace("\\r", ""))'),
    ('        pack_id,\n',
     '        str(pack_id).replace("\\n", "").replace("\\r", ""),\n')
])

fix_file("services/credential_manager.py", [
    ('session_token[-4:])', 'str(session_token[-4:]).replace("\\n", "").replace("\\r", ""))')
])

fix_file("_archive/routers/billing.py", [
    ('logger.info("Stripe webhook received: %s", event_type)',
     'logger.info("Stripe webhook received: %s", str(event_type).replace("\\n", "").replace("\\r", ""))'),
    ('logger.info("Subscription activated: customer=%s tier=%s", customer_id, tier)',
     'logger.info("Subscription activated: customer=%s tier=%s", str(customer_id).replace("\\n", "").replace("\\r", ""), str(tier).replace("\\n", "").replace("\\r", ""))'),
    ('logger.info("Subscription updated: customer=%s status=%s", customer_id, status)',
     'logger.info("Subscription updated: customer=%s status=%s", str(customer_id).replace("\\n", "").replace("\\r", ""), str(status).replace("\\n", "").replace("\\r", ""))'),
    ('logger.info("Subscription canceled: customer=%s", customer_id)',
     'logger.info("Subscription canceled: customer=%s", str(customer_id).replace("\\n", "").replace("\\r", ""))'),
    ('logger.warning("Payment failed for customer: %s", customer_id)',
     'logger.warning("Payment failed for customer: %s", str(customer_id).replace("\\n", "").replace("\\r", ""))')
])

fix_file("services/azure_pricing.py", [
    ('logger.info("Using cached prices for region %s", arm_region)',
     'logger.info("Using cached prices for region %s", str(arm_region).replace("\\n", "").replace("\\r", ""))')
])

fix_file("routers/analysis.py", [
    ('logger.error("Failed to add services for %s: %s", diagram_id, exc)',
     'logger.error("Failed to add services for %s: %s", str(diagram_id).replace("\\n", "").replace("\\r", ""), str(exc).replace("\\n", "").replace("\\r", ""))')
])

print("Patched logging vulnerabilities")
