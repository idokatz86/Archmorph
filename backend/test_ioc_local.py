from iac_chat import process_iac_chat

res = process_iac_chat('diagram1', 'test request', 'resource "azurerm_resource_group" "rg" {}', 'terraform', {})
print(res)
