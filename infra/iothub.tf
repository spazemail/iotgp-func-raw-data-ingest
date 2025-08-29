# --- 1) IoT Hub → Event Hub endpoint (identity-based) ---
resource "azurerm_iothub_endpoint_eventhub" "iothub_endpoint_eventhub_messages" {
  resource_group_name = var.resource_group
  iothub_id           = data.azurerm_iothub.iothub.id
  name                = "EventHubMessages"

  # EH namespace FQDN + entity path = your existing Event Hub
  endpoint_uri        = "sb://${data.azurerm_eventhub_namespace.eventhubs_namespace.name}.servicebus.windows.net"
  entity_path         = azurerm_eventhub.eventhub_driver_messages.name

  authentication_type = "identityBased"
}

# --- 2) RBAC: allow IoT Hub MI to send to the Event Hub ---
resource "azurerm_role_assignment" "iothub_can_send_to_eh" {
  scope                 = azurerm_eventhub.eventhub_driver_messages.id
  role_definition_name  = "Azure Event Hubs Data Sender"
  principal_id          = data.azurerm_iothub.iothub.identity[0].principal_id

  # Fail fast if MI isn't enabled but you're trying identityBased
  lifecycle {
    precondition {
      condition     = can(data.azurerm_iothub.iothub.identity[0].principal_id)
      error_message = "IoT Hub managed identity is not enabled. Enable system-assigned identity on the IoT Hub or use keyBased auth."
    }
  }
}

# --- 3) Route Raw messages to the custom EH endpoint ---
resource "azurerm_iothub_route" "iothub_route_eventhub_messages_endpoint" {
  resource_group_name = var.resource_group
  iothub_name         = data.azurerm_iothub.iothub.name
  name                = "SqlIngestionToEventHub2"

  source         = "DeviceMessages"
  condition      = "$body.MessageType = 'Raw'"
  endpoint_names = [azurerm_iothub_endpoint_eventhub.iothub_endpoint_eventhub_messages.name]
  enabled        = true
}
