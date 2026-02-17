export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-4xl items-center justify-center p-6">
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-900">The 491 Frontend</h1>
        <p className="mt-2 text-slate-600">
          Frontend module initialized with Next.js App Router, TypeScript, Tailwind,
          Firebase Auth client, and Axios API client.
        </p>
      </div>
    </main>
  );
}
