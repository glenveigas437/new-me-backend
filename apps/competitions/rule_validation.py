from django.core.exceptions import ValidationError


def validate_dependency_graph(
    season_id, rule_id=None, dependency_ids=None, additions=None
):
    """Validate the complete directed season graph; supports replacing one node or adding edges."""
    from .models import SeasonComponent

    rules = list(
        SeasonComponent.objects.filter(season_id=season_id).prefetch_related(
            "depends_on"
        )
    )
    ids = {r.id for r in rules}
    graph = {r.id: set(r.depends_on.values_list("id", flat=True)) for r in rules}
    names = {r.id: r.name or r.component.name for r in rules}
    if dependency_ids is not None:
        deps = set(dependency_ids)
        if not deps <= ids:
            raise ValidationError("Dependencies must belong to the same season.")
        node = rule_id if rule_id is not None else -1
        if node in deps:
            raise ValidationError("A rule cannot depend on itself.")
        graph[node] = deps
    for node, deps in (additions or {}).items():
        if node not in ids or not set(deps) <= ids:
            raise ValidationError("Dependencies must belong to the same season.")
        graph[node].update(deps)
    visited = set()
    active = set()
    stack = []

    def visit(node):
        if node in active:
            path = stack[stack.index(node) :] + [node]
            raise ValidationError(
                "Circular dependency: "
                + " → ".join(names.get(x, "New rule") for x in path)
            )
        if node in visited:
            return
        active.add(node)
        stack.append(node)
        for dep in graph.get(node, set()):
            visit(dep)
        stack.pop()
        active.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
