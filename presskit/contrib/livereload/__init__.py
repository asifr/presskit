"""Livereload plugin for presskit development server."""

import threading
from pathlib import Path

from presskit.hookspecs import hookimpl, FileContext, ServerContext


# Global flag to track if livereload is enabled
_livereload_enabled = False
_livereload_lock = threading.Lock()


def enable_livereload() -> None:
    """Enable livereload functionality."""
    global _livereload_enabled
    with _livereload_lock:
        _livereload_enabled = True


def disable_livereload() -> None:
    """Disable livereload functionality."""
    global _livereload_enabled
    with _livereload_lock:
        _livereload_enabled = False


def is_livereload_enabled() -> bool:
    """Check if livereload is currently enabled."""
    with _livereload_lock:
        return _livereload_enabled


# Livereload JavaScript that will be injected into HTML pages
LIVERELOAD_SCRIPT = '''
<script>
// Livereload script - watches current page and all loaded resources
let watching = new Set();
watch(location.href);

new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    watch(entry.name);
  }
}).observe({ type: "resource", buffered: true });

function watch(urlString) {
  if (!urlString) return;
  const url = new URL(urlString);
  if (url.origin !== location.origin) return;
  if (watching.has(url.pathname)) return;
  watching.add(url.pathname);

  console.log("watching", url.pathname);

  let lastModified, etag;

  async function check() {
    try {
      const res = await fetch(url, { method: "head" });
      const newLastModified = res.headers.get("Last-Modified");
      const newETag = res.headers.get("ETag");

      if ((lastModified !== undefined || etag !== undefined) &&
          (lastModified !== newLastModified || etag !== newETag)) {
        location.reload();
      }

      lastModified = newLastModified;
      etag = newETag;
    } catch (error) {
      console.warn("Livereload check failed for", url.pathname, error);
    }
  }

  setInterval(check, 1000);
}
</script>
'''


@hookimpl
def server_start(context: ServerContext) -> None:
    """Enable livereload when server starts with reload flag."""
    if context.reload:
        enable_livereload()
        print("Livereload enabled - browser will auto-refresh on changes")
    else:
        disable_livereload()


@hookimpl
def post_process_file(context: FileContext, output_path: Path) -> None:
    """Inject livereload script into HTML files when livereload is enabled."""
    if not is_livereload_enabled():
        return
    
    # Only process HTML files
    if not output_path.suffix.lower() == '.html':
        return
    
    try:
        # Read the HTML file
        with open(output_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Check if the file already contains the livereload script
        if 'watching = new Set();' in html_content:
            return
        
        # Inject the livereload script before the closing </body> tag
        if '</body>' in html_content:
            # Insert the script just before </body>
            html_content = html_content.replace('</body>', f'{LIVERELOAD_SCRIPT}\n</body>')
        elif '</html>' in html_content:
            # Fallback: insert before </html> if no </body> tag
            html_content = html_content.replace('</html>', f'{LIVERELOAD_SCRIPT}\n</html>')
        else:
            # Fallback: append to end if no closing tags found
            html_content = html_content + LIVERELOAD_SCRIPT
        
        # Write the modified HTML back to the file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
    except Exception as e:
        # Don't fail the build if livereload injection fails
        import sys
        print(f"Warning: Failed to inject livereload script into {output_path}: {e}", file=sys.stderr)