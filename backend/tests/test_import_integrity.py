"""Every `from app.X import Name` in the application names something that module actually defines.
Static (AST), so it runs even where SQLAlchemy/FastAPI are not installed -- it caught app.main failing to import
because DataQualityMetric was imported from the wrong module."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _module_path(mod):
    base = APP.parent / Path(*mod.split("."))
    return base.with_suffix(".py") if base.with_suffix(".py").exists() else (base / "__init__.py")


def _defined(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def test_every_internal_from_import_resolves():
    problems = []
    for f in sorted(list(APP.rglob("*.py")) + list((APP.parents[1] / "scripts").rglob("*.py"))):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                target = _module_path(node.module)
                if not target.exists():
                    problems.append(f"{f.name}: module {node.module} not found")
                    continue
                pkg_dir = target.parent if target.name == "__init__.py" else None
                defined = _defined(target)
                for a in node.names:
                    if a.name == "*" or a.name in defined:
                        continue
                    if pkg_dir and ((pkg_dir / f"{a.name}.py").exists() or (pkg_dir / a.name).is_dir()):
                        continue   # a submodule of the package
                    problems.append(f"{f.name}: {node.module} has no {a.name}")
    assert not problems, "\n".join(problems)


def test_every_orm_back_populates_has_its_counterpart():
    """A dangling back_populates breaks SQLAlchemy mapper configuration, so EVERY ORM query fails at runtime
    (this is what made all database-backed routes return 500). Checked statically on the model sources."""
    rels = {}   # (class, attr) -> (target class, back_populates)
    for f in (APP / "models").glob("*.py"):
        for cls in [n for n in ast.parse(f.read_text()).body if isinstance(n, ast.ClassDef)]:
            for st in cls.body:
                if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) \
                        and getattr(st.value.func, "id", None) == "relationship":
                    target = st.value.args[0].value
                    back = next((k.value.value for k in st.value.keywords if k.arg == "back_populates"), None)
                    rels[(cls.name, st.targets[0].id)] = (target, back)
    problems = []
    for (cls, attr), (target, back) in rels.items():
        if back is None:
            continue
        other = rels.get((target, back))
        if other is None:
            problems.append(f"{cls}.{attr} back_populates {target}.{back}, which does not exist")
        elif other != (cls, attr):
            problems.append(f"{cls}.{attr} <-> {target}.{back} do not point at each other")
    assert not problems, problems
