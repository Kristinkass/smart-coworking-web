"""Регистрация Swagger UI и OpenAPI JSON."""
from flask import Flask, jsonify, render_template_string

from internal.swagger.builder import build_openapi_spec

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>API — Система управления рабочими местами</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css">
  <style>body { margin: 0; }</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/openapi.json',
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: 'BaseLayout',
      persistAuthorization: true,
      tryItOutEnabled: true,
    });
  </script>
</body>
</html>
"""


def register_swagger(app: Flask) -> None:
    """Подключить /openapi.json и /docs/."""

    @app.route('/openapi.json')
    def openapi_json():
        return jsonify(build_openapi_spec(app))

    @app.route('/docs/')
    @app.route('/docs')
    def swagger_ui():
        return render_template_string(SWAGGER_UI_HTML)
