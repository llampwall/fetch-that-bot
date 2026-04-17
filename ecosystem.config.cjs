module.exports = {
  apps: [
    // Fetch - Telegram bot for social media extraction (Instagram, X, TikTok, YouTube, Reddit)
    // Managed independently from allmind so it stays up when allmind is stopped.
    {
      name: 'fetch-bot',
      script: 'P:\\software\\fetch\\.venv\\Scripts\\pythonw.exe',
      args: 'P:\\software\\fetch\\main.py',
      cwd: 'P:\\software\\fetch',
      interpreter: 'none',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      max_restarts: 100,
      min_uptime: 5000,
      exp_backoff_restart_delay: 5000,
      error_file: 'P:\\software\\fetch\\logs\\error.log',
      out_file: 'P:\\software\\fetch\\logs\\out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      max_size: '10M',
      max_memory_restart: '500M',
      windowsHide: true,
    },
  ],
};
