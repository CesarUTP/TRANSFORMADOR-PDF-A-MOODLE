import webview
import time

class Api:
    def __init__(self):
        self._window = None

    def _set_window(self, window):
        self._window = window

    def save_xml_file(self, filename, b64_content):
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("Archivos XML (*.xml)", "Todos los archivos (*.*)"),
            )
            return {"saved": True, "path": str(result)}
        except Exception as e:
            return {"saved": False, "error": str(e)}

api = Api()
html = """
<button id="btn">Test Save Dialog</button>
<div id="out"></div>
<script>
document.getElementById('btn').addEventListener('click', async () => {
    try {
        const result = await window.pywebview.api.save_xml_file('test.xml', 'YmFzZTY0');
        document.getElementById('out').innerText = JSON.stringify(result);
    } catch (e) {
        document.getElementById('out').innerText = 'Error: ' + e.toString() + ' | ' + e.message;
    }
});
</script>
"""

window = webview.create_window('Test', html=html, js_api=api)
api._set_window(window)
webview.start()
