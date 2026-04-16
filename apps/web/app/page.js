const services = [
  {
    name: "API",
    summary: "FastAPI service for future backend interfaces.",
    entry: "python -m apps.api",
    health: "http://127.0.0.1:8000/health",
  },
  {
    name: "Worker",
    summary: "Celery worker with registered bootstrap tasks.",
    entry: "python -m apps.worker",
    health: "python -m apps.worker.healthcheck",
  },
  {
    name: "Web",
    summary: "Next.js runtime shell for future user-facing pages.",
    entry: "npm run web:dev",
    health: "http://127.0.0.1:3000/api/health",
  },
];

export default function HomePage() {
  return (
    <main className="page-shell">
      <section className="hero">
        <p className="eyebrow">TASK-002 Runtime Entry</p>
        <h1>aisecurity can now boot API, Worker, and Web independently.</h1>
        <p className="subtitle">
          This page is the minimal Next.js entry for local bring-up. It exposes
          the runtime commands and health-check targets that the next tasks will
          build on.
        </p>
      </section>

      <section className="grid">
        {services.map((service) => (
          <article key={service.name} className="card">
            <p className="card-label">{service.name}</p>
            <p className="card-summary">{service.summary}</p>
            <div className="detail-block">
              <span className="detail-title">Start</span>
              <code>{service.entry}</code>
            </div>
            <div className="detail-block">
              <span className="detail-title">Health</span>
              <code>{service.health}</code>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
