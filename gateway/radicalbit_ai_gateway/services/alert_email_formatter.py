from typing import Any


def build_alert_email_subject(rule_name: str, route_name: str) -> str:
    """Build the email subject line for an alert notification."""
    return f'[Alert Notification] {rule_name} triggered on {route_name}'


def build_alert_email_body(
    rule_name: str,
    description: str | None,
    project_uuid: str,
    route_name: str,
    event_name: str,
    event_details: dict[str, Any] | None = None,
) -> str:
    """Build the HTML body for an alert notification email."""
    details = event_details or {}
    req_uuid = details.get('request_uuid', 'N/A')
    project_name = details.get('project_name', 'N/A')
    api_key_name = details.get('api_key_name', 'N/A')
    group_name = details.get('group_name', 'N/A')

    g_name = details.get('name', 'N/A')
    g_type = details.get('type', 'N/A')
    g_where = details.get('where', 'N/A')
    g_behavior = details.get('behavior', 'N/A')
    g_params = details.get('parameters', 'N/A')

    cache_type = details.get('cache_type')
    fallback_target = details.get('target')
    fallback_dest = details.get('fallback')

    extra_rows = ''
    if g_name != 'N/A':
        extra_rows += (
            f"<tr><td style='padding: 8px; font-weight: bold;'>Guardrail Name:</td>"
            f"<td style='padding: 8px;'>{g_name}</td></tr>"
            f"<tr><td style='padding: 8px; font-weight: bold;'>Guardrail Type:</td>"
            f"<td style='padding: 8px;'>{g_type}</td></tr>"
            f"<tr><td style='padding: 8px; font-weight: bold;'>Phase (Where):</td>"
            f"<td style='padding: 8px;'>{g_where}</td></tr>"
            f"<tr><td style='padding: 8px; font-weight: bold;'>Behavior:</td>"
            f"<td style='padding: 8px;'>{g_behavior}</td></tr>"
            f"<tr><td style='padding: 8px; font-weight: bold;'>Parameters:</td>"
            f"<td style='padding: 8px; font-family: monospace;'>{g_params}</td></tr>"
        )
    if cache_type:
        extra_rows += (
            f"<tr><td style='padding: 8px; font-weight: bold;'>Cache Type:</td>"
            f"<td style='padding: 8px;'>{cache_type}</td></tr>"
        )
    if fallback_target:
        extra_rows += (
            f"<tr><td style='padding: 8px; font-weight: bold;'>Fallback:</td>"
            f"<td style='padding: 8px;'>{fallback_target} &rarr; {fallback_dest}</td></tr>"
        )

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 650px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; color: #333; background-color: #ffffff;">
        <h2 style="color: #e53e3e; margin-top: 0;">🚨 Alert Notification</h2>
        <p style="font-size: 14px; color: #555;">An alert rule has been triggered on your Radicalbit AI Gateway.</p>

        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
            <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0; width: 35%;">Rule Name:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{rule_name}</td></tr>
            <tr><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Description:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{description or 'N/A'}</td></tr>
            <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Project:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{project_name} <span style="font-size: 12px; color: #718096;">({project_uuid})</span></td></tr>
            <tr><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Route:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{route_name}</td></tr>
            <tr style="background-color: #f7fafc;"><td style="padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0;">Event:</td><td style="padding: 10px; border-bottom: 1px solid #e2e8f0; color: #c53030; font-weight: bold;">{event_name}</td></tr>
        </table>

        <h3 style="color: #2d3748; border-bottom: 2px solid #edf2f7; padding-bottom: 8px; margin-top: 25px;">Event Details</h3>
        <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
            <tr><td style="padding: 8px; font-weight: bold; width: 35%;">Request UUID:</td><td style="padding: 8px; font-family: monospace;">{req_uuid}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">API Key:</td><td style="padding: 8px;">{api_key_name}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Group:</td><td style="padding: 8px;">{group_name}</td></tr>
            {extra_rows}
        </table>

        <div style="margin-top: 25px; padding-top: 15px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #a0aec0;">
            Radicalbit AI Gateway &bull; Alerting System
        </div>
    </div>
    """
