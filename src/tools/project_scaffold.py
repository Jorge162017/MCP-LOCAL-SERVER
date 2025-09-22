# src/tools/project_scaffold.py
from __future__ import annotations
from typing import Dict, Any, List
from pathlib import Path
import subprocess
import html

tool_spec = {
    "name": "project_scaffold",
    "description": "Genera estructura base de proyecto (carpetas y archivos). Opcional: inicializa repo git y hace commit.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dir": {"type": "string", "description": "Ruta del nuevo proyecto (se creará si no existe)."},
            "name": {"type": "string", "description": "Nombre del proyecto a poner en README."},
            "with_git": {"type": "boolean", "description": "Si true: git init → add → commit", "default": True},
            "python_pkg": {"type": "boolean", "description": "Si true: crea src/<package>/__init__.py", "default": True},
            "package_name": {"type": "string", "description": "Nombre del paquete si python_pkg=true", "default": "app"},
            "requirements": {"type": "array", "items": {"type": "string"}, "description": "Librerías a incluir en requirements.txt"},
        },
        "required": ["dir", "name"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "created": {"type": "array", "items": {"type": "string"}},
            "git": {"type": "object"}
        }
    }
}

README_TPL = """# {name}

Estructura generada con `project_scaffold`.

## Estructura

{tree}

## Requisitos
- Python 3.10+

## Uso
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```
"""

GITIGNORE_TPL = """__pycache__/
.venv/
.DS_Store
reports/
*.log
"""

MAIN_PY = """def main():
    print("Hola desde {name}!")

if __name__ == "__main__":
    main()
"""

def _run_git(dirp: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(dirp), text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

def _tree_str(root: Path) -> str:
    lines = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir():
            lines.append(str(rel) + "/")
        else:
            lines.append(str(rel))
    return "\n".join(lines) if lines else "(vacío)"

def run(args: Dict[str, Any]) -> Dict[str, Any]:
    dirp = Path(args["dir"]).expanduser().resolve()
    name = args["name"].strip()
    with_git = bool(args.get("with_git", True))
    python_pkg = bool(args.get("python_pkg", True))
    package_name = args.get("package_name", "app").strip() or "app"
    requirements = args.get("requirements") or []

    created: List[str] = []
    dirp.mkdir(parents=True, exist_ok=True)

    # carpetas base
    (dirp / "src").mkdir(exist_ok=True)
    (dirp / "reports").mkdir(exist_ok=True)
    if python_pkg:
        pkg_dir = dirp / "src" / package_name
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        created.append(str(pkg_dir / "__init__.py"))

    # archivos base
    (dirp / ".gitignore").write_text(GITIGNORE_TPL, encoding="utf-8")
    created.append(str(dirp / ".gitignore"))

    (dirp / "requirements.txt").write_text("\n".join(requirements) + ("\n" if requirements else ""), encoding="utf-8")
    created.append(str(dirp / "requirements.txt"))

    (dirp / "main.py").write_text(MAIN_PY.format(name=name), encoding="utf-8")
    created.append(str(dirp / "main.py"))

    # README (con tree)
    tree = _tree_str(dirp)
    (dirp / "README.md").write_text(README_TPL.format(name=name, tree=tree), encoding="utf-8")
    created.append(str(dirp / "README.md"))

    git_res = {}
    if with_git:
        cp_init = _run_git(dirp, ["init"])
        _run_git(dirp, ["config", "user.name", "MCP Bot"])
        _run_git(dirp, ["config", "user.email", "mcp@example.local"])
        cp_add = _run_git(dirp, ["add", "."])
        cp_commit = _run_git(dirp, ["commit", "-m", f"scaffold: {name}"])
        git_res = {
            "init_rc": cp_init.returncode, "init_out": cp_init.stdout, "init_err": cp_init.stderr,
            "add_rc": cp_add.returncode, "commit_rc": cp_commit.returncode,
            "commit_out": cp_commit.stdout, "commit_err": cp_commit.stderr,
        }

    return {"created": created, "git": git_res}