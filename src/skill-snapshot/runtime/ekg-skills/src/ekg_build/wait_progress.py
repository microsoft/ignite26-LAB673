from ekg_core.models import BuildSpec

from .executor import BuildError, _sync_checkpoint, _sync_status, index_names

def progress(executor, spec: BuildSpec) -> dict:
        """Read live managed synchronization progress; performs no writes."""
        name = index_names(spec)["knowledge_source"]
        status = executor.adapter.knowledge_source_status(name)
        current = status.get("currentSynchronizationState") or {}
        last = status.get("lastSynchronizationState") or {}
        error = None
        try:
            finished = _sync_status(status) is not None
        except BuildError as failure:
            finished, error = False, str(failure)
        checkpoint = _sync_checkpoint(status)
        state = current if current else last
        status_name = "failed" if error else "synchronized" if finished else (
            "continuing" if checkpoint else "synchronizing")
        return {
            "phase": "build.progress", "knowledge_source": name,
            "status": status_name,
            "items_processed": state.get("itemsUpdatesProcessed"),
            "items_failed": state.get("itemsUpdatesFailed"),
            "document_count": spec.source_manifest.document_count if spec.source_manifest else None,
            "started_at": state.get("startTime"), "finished_at": last.get("endTime"),
            "error": error, "evidence_origin": "live_knowledge_source_status",
            "next_action": (
                "Reconcile this exact attempt read-only before publish." if finished else
                "Do not retry writes; reconcile read-only and inspect the generated indexer." if error else
                "Indexer reached the normal 120-minute checkpoint; the next scheduled run continues it." if checkpoint else
                "Synchronization is still running; check again later or reconcile when finished."
            ),
        }
