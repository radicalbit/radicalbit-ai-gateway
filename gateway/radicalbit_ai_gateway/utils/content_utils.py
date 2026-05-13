import json


class ContentUtils:
    """Utility class for content processing operations."""

    @staticmethod
    def extract_text_content(
        content: str | list | dict | bytes | bytearray | None,
        strip: bool = False,
    ) -> str:
        """Extract text content from various content formats.

        Handles multiple content types commonly used in LLM messages:
        - str: return as is (optionally stripped)
        - list: recursively extract and join textual parts with spaces
        - dict: if {"type":"text","text":"..."} return its text,
                else try "content" key if it's a string
        - bytes/bytearray: decode as UTF-8 if possible
        - None: return empty string

        Args:
            content: The content to extract text from. Can be a plain string,
                    a list of content blocks (e.g., [{'type': 'text', 'text': '...'}]),
                    a dict, bytes, or None.
            strip: If True, strip whitespace from the result.

        Returns:
            The extracted text as a single string.

        """
        if content is None:
            return ''

        if isinstance(content, str):
            return content.strip() if strip else content

        if isinstance(content, list):
            parts = []
            for item in content:
                text = ContentUtils.extract_text_content(item, strip=strip)
                if text:
                    parts.append(text)
            return ' '.join(parts)

        if isinstance(content, dict):
            if content.get('type') == 'text':
                val = content.get('text')
                if isinstance(val, str):
                    return val.strip() if strip else val
                return '' if val is None else str(val)
            if isinstance(content.get('content'), str):
                val = content['content']
                return val.strip() if strip else val
            return ''

        if isinstance(content, bytes | bytearray):
            try:
                decoded = content.decode('utf-8')
                return decoded.strip() if strip else decoded
            except Exception:
                return ''

        return ''

    @staticmethod
    def normalize_openai_message_content(
        content: str | list | None,
    ) -> str | None:
        """Normalize ChatCompletionMessage.content to avoid double-encoded JSON arrays.

        Content can be either a plain string or a list of blocks
        (e.g., [{'type':'text','text':'...'}]).
        Always return a plain string (or None). If it's a string that represents
        a valid JSON array of blocks, convert it by concatenating the 'text' fields;
        if it's already a list of blocks, join them.

        Args:
            content: The content to normalize (string, list, or None).

        Returns:
            A normalized plain string, or None if input was None.

        """
        if content is None:
            return None
        # If it's already a list (multi-modal blocks), join text parts into a string
        if isinstance(content, list):
            return ContentUtils.extract_text_content(content)
        # If it's a string and looks like a JSON array, try to parse it
        if isinstance(content, str):
            s = content.strip()
            if s.startswith('[') and s.endswith(']'):
                try:
                    parsed = json.loads(s)
                    # Ensure it's a list of 'type'/'text' blocks then join texts
                    if isinstance(parsed, list) and all(
                        isinstance(b, dict) and 'type' in b for b in parsed
                    ):
                        return ContentUtils.extract_text_content(parsed)
                except Exception:
                    # Not valid JSON or not the expected format: keep the string
                    return content
        return content
