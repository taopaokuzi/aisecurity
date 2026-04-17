from __future__ import annotations

import unittest

from packages.prompts import PromptLoader, PromptNotFoundError, PromptRenderError


class PromptLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = PromptLoader()

    def test_load_returns_template_from_default_directory(self) -> None:
        template = self.loader.load("parse_permission_request")

        self.assertEqual(template.name, "parse_permission_request")
        self.assertTrue(template.path.name.endswith("parse_permission_request.md"))
        self.assertIn("权限申请解析器", template.content)

    def test_render_substitutes_template_variables(self) -> None:
        rendered = self.loader.render(
            "parse_permission_request",
            {"request_text": "我需要查看销售部 Q3 报表"},
        )

        self.assertIn("我需要查看销售部 Q3 报表", rendered.content)

    def test_load_raises_clear_error_when_prompt_is_missing(self) -> None:
        with self.assertRaises(PromptNotFoundError) as context:
            self.loader.load("missing_prompt")

        self.assertIn("missing_prompt", str(context.exception))

    def test_render_raises_clear_error_when_variable_is_missing(self) -> None:
        with self.assertRaises(PromptRenderError) as context:
            self.loader.render("parse_permission_request")

        self.assertIn("request_text", str(context.exception))


if __name__ == "__main__":
    unittest.main()
