# Trial, update, retire

## Use this path

Use this path for three mutable follow-ons: an OWL trial build, an in-place update of an already published generation, or retirement of unbound generations.

## OWL trial

Offer a trial by default when `ontology_mode` is `owl_file` and the user has not already declined one.

1. Plan the trial from the same BuildSpec shape, but with the sample setting on the CLI surface.
2. After exact approval, run `ekg-build apply` for the trial generation.
3. Run `ekg-build trial-report` after synchronization. Report the short summary, zero-hit classes or predicates, and whether the decision is go or no-go.
4. A trial is never publishable. Cleanup requires its own approved retire plan.

## In-place update

Use this only when documents changed but the published generation keeps the same ontology, models, extraction settings, and source location.

1. Read the published descriptor and the new source manifest.
2. After approval of the update plan ID, use `ekg-build update`.
3. If update reports waiting or stopped, follow its single `next_step`. Re-running the same approved update resumes that exact plan.
4. If the review says rebuild is required, stop using update and return to the normal build plan path.

## Retire old generations

1. List protected generations with `ekg-skills-ekg_build_generations`, passing every serving descriptor path that must stay protected.
2. Retire only unbound generations after a separate CLI review with `ekg-build plan-retire`.
3. Wait for `approved <plan-id>` before `ekg-build retire`.
4. Deletion is conditional on the reviewed ETag set. Never claim a generation is safe to delete without the fresh generation listing.

## Return

Separate measured evidence from proposed cleanup. State what was only reviewed, what was actually updated or deleted, and what still needs explicit approval.
