"""
Make the Flutter code compatible with runtime design tokens.

The design tokens (AppColors, AppTypography, AppFonts, AppRadius, AppShadows) become getters that read the current
design version and brightness, so no expression that uses them can be `const`. This script removes the `const`
keyword from every const expression whose extent references a token, and turns const declarations that do into
`final` ones (cascading: a declaration that became final is itself a dynamic name for the next pass).

Constructor declarations (`const Foo({...});`) are never touched. Default parameter values that use a token cannot
be fixed automatically; they are reported for a manual change.

Usage: python3 scripts/frontend/deconst_tokens.py flutter_app/lib [--check]
"""
import re
import sys
from pathlib import Path

TOKENS = {"AppColors", "AppTypography", "AppFonts", "AppRadius", "AppShadows"}


def tokenize(src):
    """[(kind, text, start, end)] with kind in ident, punct, string, comment, ws, num."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            j = i
            while j < n and src[j].isspace():
                j += 1
            out.append(("ws", src[i:j], i, j)); i = j; continue
        if src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            out.append(("comment", src[i:j], i, j)); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i) + 2
            out.append(("comment", src[i:j], i, j)); i = j; continue
        if c in "'\"" or (c == "r" and i + 1 < n and src[i + 1] in "'\""):
            j = i
            raw = c == "r"
            if raw:
                j += 1
            q = src[j:j + 3] if src[j:j + 3] in ("'''", '"""') else src[j]
            j += len(q)
            while j < n and not src.startswith(q, j):
                if src[j] == "\\" and not raw:
                    j += 2; continue
                if src.startswith("${", j) and not raw:
                    depth, j = 1, j + 2
                    while j < n and depth:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                        elif src[j] in "'\"":  # nested string inside interpolation
                            qq = src[j]; j += 1
                            while j < n and src[j] != qq:
                                j += 2 if src[j] == "\\" else 1
                        j += 1
                    continue
                j += 1
            j += len(q)
            out.append(("string", src[i:j], i, j)); i = j; continue
        if c.isalpha() or c == "_" or c == "$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            out.append(("ident", src[i:j], i, j)); i = j; continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            out.append(("num", src[i:j], i, j)); i = j; continue
        out.append(("punct", c, i, i + 1)); i += 1
    return out


OPEN = {"(": ")", "[": "]", "{": "}"}


def sig(toks):
    return [t for t in toks if t[0] not in ("ws", "comment")]


def match(st, k):
    """index (in st) of the bracket closing st[k]."""
    o = st[k][1]; c = OPEN[o]; depth = 0
    for m in range(k, len(st)):
        if st[m][0] == "punct":
            if st[m][1] == o:
                depth += 1
            elif st[m][1] == c:
                depth -= 1
                if depth == 0:
                    return m
    raise ValueError("unbalanced")


def match_angle(st, k):
    depth = 0
    for m in range(k, len(st)):
        if st[m][1] == "<":
            depth += 1
        elif st[m][1] == ">":
            depth -= 1
            if depth == 0:
                return m
    raise ValueError("unbalanced <>")


def refs(st, a, b, names):
    for m in range(a, b + 1):
        if st[m][0] == "ident" and st[m][1] in names:
            return True
    return False


def process(src, names):
    """Returns (new_src, changed, new_dynamic_names, default_param_problems)."""
    toks = tokenize(src)
    st = sig(toks)
    edits = []  # (start, end, replacement)
    new_names = set()
    for k, t in enumerate(st):
        if t[0] != "ident" or t[1] != "const":
            continue
        prev = st[k - 1][1] if k else ";"
        nxt = st[k + 1]
        # ---- declarations: [static] const [Type] name = expr ;
        is_decl_ctx = prev in (";", "{", "}", "static") or (k and st[k - 1][0] == "punct" and prev == ")"
                                                              and False)
        if is_decl_ctx:
            # constructor declaration? const Name( ... ) followed by ; : { =>
            m = k + 1
            if st[m][0] == "ident":
                mm = m + 1
                if mm < len(st) and st[mm][1] == "." and st[mm + 1][0] == "ident":
                    mm += 2
                if mm < len(st) and st[mm][1] == "(":
                    close = match(st, mm)
                    after = st[close + 1][1] if close + 1 < len(st) else ";"
                    if after in (";", ":", "{", "=>") and prev in (";", "{", "}"):
                        continue  # constructor declaration
            # find '=' then ';' at depth 0
            j, eq, depth = k + 1, None, 0
            while j < len(st):
                v = st[j][1]
                if st[j][0] == "punct":
                    if v in "([{":
                        depth += 1
                    elif v in ")]}":
                        depth -= 1
                    elif v == "=" and depth == 0 and eq is None:
                        eq = j
                    elif v == ";" and depth == 0:
                        break
                j += 1
            if eq is None:
                continue
            name = st[eq - 1][1]
            if refs(st, eq + 1, j, names):
                edits.append((t[2], t[3], "final"))
                new_names.add(name)
            continue
        # ---- expressions: const Type(...) / const Type.named(...) / const [..] / const {..} / const <T>[..]
        a = k + 1
        if nxt[1] in ("[", "{", "("):
            b = match(st, a)
        elif nxt[1] == "<":
            g = match_angle(st, a)
            b = match(st, g + 1)
        elif nxt[0] == "ident":
            m = a + 1
            while m < len(st) and st[m][1] == "." and st[m + 1][0] == "ident":
                m += 2
            if m < len(st) and st[m][1] == "<":
                m = match_angle(st, m) + 1
                while m < len(st) and st[m][1] == "." and st[m + 1][0] == "ident":
                    m += 2
            if m < len(st) and st[m][1] == "(":
                b = match(st, m)
            else:
                continue
        else:
            continue
        if refs(st, a, b, names):
            # remove 'const' and the whitespace after it
            end = t[3]
            while end < len(src) and src[end] == " ":
                end += 1
            edits.append((t[2], end, ""))
    # default parameter values: `this.x = AppColors.y` or `Type x = AppColors.y` inside a parameter list
    problems = []
    for m in re.finditer(r"(this\.\w+|\b\w+\s+\w+)\s*=\s*(App(?:Colors|Typography|Fonts|Radius|Shadows))\.\w+", src):
        line = src.count("\n", 0, m.start()) + 1
        # only inside a parameter list: crude check, an opening '{' or '(' of a parameter list on the same logical line
        problems.append((line, m.group(0)))
    if not edits:
        return src, False, new_names, problems
    out = src
    for s, e, rep in sorted(edits, reverse=True):
        out = out[:s] + rep + out[e:]
    return out, True, new_names, problems


def main():
    root = Path(sys.argv[1])
    check = "--check" in sys.argv
    files = sorted(root.rglob("*.dart"))
    names = set(TOKENS)
    for _ in range(10):
        any_change = False
        added = set()
        for f in files:
            src = f.read_text()
            new, changed, new_names, _ = process(src, names)
            added |= new_names
            if changed:
                any_change = True
                if not check:
                    f.write_text(new)
        if not (added - names) and not any_change:
            break
        names |= added
        if check:
            break
    print("dynamic names:", sorted(names - TOKENS))
    for f in files:
        _, changed, _, problems = process(f.read_text(), names)
        if changed:
            print("STILL CONST:", f)
        for line, text in problems:
            print(f"DEFAULT PARAM? {f}:{line}: {text}")


if __name__ == "__main__":
    main()
