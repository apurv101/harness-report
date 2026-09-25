// Runs on every viewer request, on every behaviour.
//
// Two jobs, both of which exist so the Lambda behind CloudFront sees one host and one shape:
//   1. www -> apex, 301.  CloudFront cannot forward the viewer's Host header to a Lambda function
//      URL origin, so the Lambda is told one host in its environment.  Collapsing to a single
//      canonical host is what keeps serve.py's same-origin check on POST honest.
//   2. extensionless paths -> /index.html, so the app's own routes (/#/runs is a hash, but the
//      legacy /<run-id> links are not) load the SPA instead of a 404 out of S3.
function handler(event) {
  var request = event.request;
  var host = request.headers.host ? request.headers.host.value : '';

  if (host.indexOf('www.') === 0) {
    var query = '';
    for (var key in request.querystring) {
      var value = request.querystring[key];
      query += (query ? '&' : '?') + key + (value.value ? '=' + value.value : '');
    }
    return {
      statusCode: 301,
      statusDescription: 'Moved Permanently',
      headers: { location: { value: 'https://' + host.slice(4) + request.uri + query } }
    };
  }

  var uri = request.uri;
  if (uri.indexOf('/api/') === 0 || uri.indexOf('/auth/') === 0 || uri.indexOf('/raw/') === 0) return request;
  // Pages serve.py renders itself (their own <head>, and .md / .json twins), and what agents read.
  if (/^\/(harnesses|tasks|runs)(\/|\.|$)/.test(uri) || uri === '/mcp' || /^\/(llms(-full)?\.txt|sitemap\.xml|sitemaps\/)/.test(uri)) return request;

  // An allowlist, not "does the last segment contain a dot".  evals.py builds a run id out of a
  // repo slug that keeps dots (dlants/magenta.nvim -> ...magenta.nvim), so a legacy /<run-id> link
  // can look like a filename and would 404 out of the bucket under the dot rule.  web/dist holds
  // assets/ plus five known files, so naming the extensions is both exact and short.
  if (uri.indexOf('/assets/') === 0) return request;
  if (/\.(html|js|css|svg|png|webp|ico|woff2|txt|xml|json|map)$/.test(uri)) return request;

  if (uri !== '/') request.uri = '/index.html';
  return request;
}
