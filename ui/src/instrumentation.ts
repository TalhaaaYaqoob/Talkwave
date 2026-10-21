export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    // Enable source map support for better stack traces
    if (process.env.NODE_ENV === 'development') {
      const sourceMapSupport = await import('source-map-support');
      sourceMapSupport.install();
    }
  }
}
