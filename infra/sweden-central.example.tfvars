# Example variables for a future isolated Sweden Central stack.
#
# Do not use this with the current West Europe Terraform state key.
# Copy to an operator-local tfvars file only after a separate backend key,
# workspace, or environment folder has been approved for #783.

# subscription_id = Set via TF_VAR_subscription_id or an operator-local tfvars file.
location        = "swedencentral"
openai_location = "swedencentral"
environment     = "dev"

# Keep global URLs and secrets operator-owned. Do not commit real values here.
frontend_url      = "https://archmorphai.com"
db_admin_username = "archmorphadmin"
# db_admin_password = Set via TF_VAR_db_admin_password or an approved secret store.

# Match current West Europe baseline until Sweden Central quota proves otherwise.
openai_capacity = 10

# DR stays disabled for the parallel build unless the change request explicitly
# validates an additional secondary region and cost envelope.
enable_dr = false