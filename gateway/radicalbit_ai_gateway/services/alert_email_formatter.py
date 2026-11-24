from collections.abc import Sequence
from datetime import datetime
import html

_LABEL = (
    'padding: 10px; font-weight: bold; border-bottom: 1px solid #e2e8f0; width: 35%;'
)
_VALUE = 'padding: 10px; border-bottom: 1px solid #e2e8f0;'


def build_alert_email_subject(rule_name: str, event: str, target: str) -> str:
    """Build the email subject line for an alert: rule, event and target."""
    return f'[Alert] {rule_name}: {event} on {target}'


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="{_LABEL}">{html.escape(label)}:</td>'
        f'<td style="{_VALUE}">{html.escape(value)}</td></tr>'
    )


def build_alert_email_body(
    *,
    rule_name: str,
    description: str | None,
    scope: str,
    target: str,
    event: str,
    time: datetime,
    details: Sequence[tuple[str, str]],
) -> str:
    """Build the HTML body of an alert email, with every value escaped.

    The rule, scope, target, event and time are always shown. `details` are the
    rows the rule's aggregation adds. Request content never reaches them.
    """
    rows = [_row('Rule', rule_name)]
    if description:
        rows.append(_row('Description', description))
    rows += [
        _row('Scope', scope),
        _row('Target', target),
        _row('Event', event),
        _row('Time', time.strftime('%Y-%m-%d %H:%M:%S UTC')),
    ]
    details_section = ''
    if details:
        details_section = (
            '<h3 style="color: #2d3748; border-bottom: 2px solid #edf2f7; '
            'padding-bottom: 8px; margin-top: 25px;">Details</h3>'
            '<table style="width: 100%; border-collapse: collapse;">'
            + ''.join(_row(label, value) for label, value in details)
            + '</table>'
        )

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 650px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; color: #333; background-color: #ffffff;">
        <h2 style="color: #e53e3e; margin-top: 0;">🚨 Alert Notification</h2>
        <p style="font-size: 14px; color: #555;">An alert rule has been triggered on your Radicalbit AI Gateway.</p>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">{''.join(rows)}</table>
        {details_section}
        <div style="margin-top: 25px; padding-top: 15px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #a0aec0;">
            Radicalbit AI Gateway &bull; Alerting System
        </div>
    </div>
    """
