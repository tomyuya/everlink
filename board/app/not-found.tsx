import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Decision not found
      </p>
      <p className="mt-1 max-w-sm text-xs text-zinc-500 dark:text-zinc-400">
        It may have expired or never existed. The inbox always reflects the current
        queue.
      </p>
      <Link
        href="/"
        className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-sky-600 hover:underline dark:text-sky-400"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to inbox
      </Link>
    </div>
  );
}
