"""
latex_texto.py — fórmulas \\( … \\) como texto Unicode, para el PDF del examen.

ReportLab no dibuja LaTeX, y traer matplotlib o un motor TeX solo para esto
sería muy pesado. Se convierte lo común en un examen (potencias, subíndices,
fracciones sencillas, raíces, letras griegas, operadores, flechas) a texto
Unicode; lo que no se entiende (matrices, integrales con límites largos,
comandos raros) NO se adivina: la fórmula se deja escrita tal cual, entre \\( y
\\), para que el docente la vea y no cambie su significado.

    formulas_a_texto("Si \\(x^2 + \\alpha \\leq 3\\) entonces…") → "Si x² + α ≤ 3 entonces…"
    latex_a_texto("\\frac{1}{2}")                                → "½"   (None si no se puede)

Solo emite caracteres que DejaVu Sans (la fuente del PDF) tiene: la prueba
dev/test_exportar_pdf.py lo comprueba contra el archivo de la fuente.
"""

import re
from typing import Callable, List, Optional, Tuple

_FORMULA = re.compile(r"\\\(([\s\S]+?)\\\)")


class _NoConvertible(Exception):
    """La fórmula tiene algo que esta conversión no sabe escribir como texto."""


_SIMBOLOS = {
    # letras griegas
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # operadores y relaciones
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈",
    "equiv": "≡", "sim": "∼", "propto": "∝", "ll": "≪", "gg": "≫",
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫",
    "oint": "∮", "degree": "°", "circ": "∘", "prime": "′",
    # conjuntos y lógica
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "varnothing": "∅", "setminus": "∖",
    "forall": "∀", "exists": "∃", "neg": "¬", "lnot": "¬", "land": "∧", "wedge": "∧",
    "lor": "∨", "vee": "∨", "therefore": "∴", "because": "∵",
    # flechas
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "implies": "⇒", "iff": "⇔",
    "uparrow": "↑", "downarrow": "↓", "mapsto": "↦",
    # puntos
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮",
}

_FUNCIONES = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "lim", "max", "min",
              "exp", "det", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "gcd", "mod"}
_TEXTO = {"text", "mathrm", "textrm", "mathbf", "textbf", "mathit", "textit", "mathsf", "operatorname"}
_PIZARRA = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ"}
_ESPACIOS = {",", ";", ":", " ", "!", "quad", "qquad"}
_SIN_EFECTO = {"left", "right", "displaystyle", "textstyle", "big", "Big", "bigg", "Bigg"}
_ESCAPADOS = {"%": "%", "$": "$", "&": "&", "#": "#", "_": "_", "{": "{", "}": "}"}

_SUPER = dict(zip("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"))
_SUB = dict(zip("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"))
_SUB.update({"a": "ₐ", "e": "ₑ", "o": "ₒ", "x": "ₓ", "h": "ₕ", "k": "ₖ", "l": "ₗ", "m": "ₘ",
             "n": "ₙ", "p": "ₚ", "s": "ₛ", "t": "ₜ"})

_FRACCIONES = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼",
               ("3", "4"): "¾", ("1", "5"): "⅕", ("1", "8"): "⅛"}


def _con_marcas(s: str, tabla: dict, marca: str) -> str:
    """`s` en super/subíndices si TODOS sus caracteres existen; si no, ^(…) o _(…)."""
    if s and all(c in tabla for c in s):
        return "".join(tabla[c] for c in s)
    return marca + (s if len(s) == 1 else f"({s})")


class _Lector:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def fin(self) -> bool:
        return self.i >= len(self.s)

    def secuencia(self, hasta_llave: bool) -> str:
        out: List[str] = []
        while not self.fin():
            c = self.s[self.i]
            if c == "}":
                if hasta_llave:
                    self.i += 1
                    return "".join(out)
                raise _NoConvertible("llave sin abrir")
            self.i += 1
            if c == "{":
                out.append(self.secuencia(True))
            elif c == "\\":
                out.append(self._comando())
            elif c in "^_":
                arg = self._argumento()
                out.append(_con_marcas(arg, _SUPER if c == "^" else _SUB, c))
            elif c == "~":
                out.append(" ")
            elif c in "&$":
                raise _NoConvertible("tabla o modo matemático anidado")
            else:
                out.append(c)
        if hasta_llave:
            raise _NoConvertible("llave sin cerrar")
        return "".join(out)

    def _argumento(self) -> str:
        """El argumento de ^, _, \\frac…: un grupo {…} o UN solo símbolo."""
        while not self.fin() and self.s[self.i] == " ":
            self.i += 1
        if self.fin():
            raise _NoConvertible("falta un argumento")
        c = self.s[self.i]
        self.i += 1
        if c == "{":
            return self.secuencia(True)
        if c == "\\":
            return self._comando()
        if c == "}":
            raise _NoConvertible("falta un argumento")
        return c

    def _texto_crudo(self) -> str:
        """Lo que hay entre llaves, sin interpretar (\\text{si } x…)."""
        if self.fin() or self.s[self.i] != "{":
            return self._argumento()
        self.i += 1
        nivel, ini = 1, self.i
        while not self.fin():
            ch = self.s[self.i]
            nivel += (ch == "{") - (ch == "}")
            self.i += 1
            if nivel == 0:
                return self.s[ini:self.i - 1]
        raise _NoConvertible("llave sin cerrar")

    def _comando(self) -> str:
        m = re.compile(r"[A-Za-z]+").match(self.s, self.i)
        if not m:
            if self.fin():
                raise _NoConvertible("barra al final")
            c = self.s[self.i]
            self.i += 1
            if c in _ESPACIOS:
                return "" if c == "!" else " "
            if c in _ESCAPADOS:
                return _ESCAPADOS[c]
            if c == "\\":
                raise _NoConvertible("salto de línea")      # matrices, alineaciones…
            raise _NoConvertible(f"\\{c}")
        nombre = m.group(0)
        self.i = m.end()
        if nombre in _SIMBOLOS:
            return _SIMBOLOS[nombre]
        if nombre in _FUNCIONES:
            return nombre
        if nombre in _SIN_EFECTO:
            if nombre in ("left", "right") and not self.fin() and self.s[self.i] == ".":
                self.i += 1
            return ""
        if nombre in _ESPACIOS:
            return " "
        if nombre in _TEXTO:
            return self._texto_crudo()
        if nombre == "mathbb":
            letra = self._texto_crudo()
            if letra not in _PIZARRA:
                raise _NoConvertible("mathbb")
            return _PIZARRA[letra]
        if nombre == "frac":
            return self._fraccion(self._argumento(), self._argumento())
        if nombre == "sqrt":
            indice = ""
            if not self.fin() and self.s[self.i] == "[":
                fin = self.s.find("]", self.i)
                if fin < 0:
                    raise _NoConvertible("raíz sin cerrar")
                indice, self.i = self.s[self.i + 1:fin], fin + 1
            rad = self._argumento()
            raiz = {"": "√", "2": "√", "3": "∛", "4": "∜"}.get(indice)
            if raiz is None:
                raise _NoConvertible("índice de raíz")
            return raiz + (rad if len(rad) == 1 or rad.isalnum() else f"({rad})")
        raise _NoConvertible(f"\\{nombre}")

    @staticmethod
    def _fraccion(a: str, b: str) -> str:
        a, b = a.strip(), b.strip()
        if (a, b) in _FRACCIONES:
            return _FRACCIONES[(a, b)]
        sencillo = lambda t: bool(re.fullmatch(r"[\w.,]+", t))
        return f"{a if sencillo(a) else '(' + a + ')'}/{b if sencillo(b) else '(' + b + ')'}"


def latex_a_texto(latex: str) -> Optional[str]:
    """El LaTeX de UNA fórmula como texto Unicode; None si no se puede escribir
    sin perder su sentido."""
    try:
        lector = _Lector(latex)
        out = lector.secuencia(False)
    except _NoConvertible:
        return None
    return re.sub(r" {2,}", " ", out).strip()


def formulas_a_texto(texto: str) -> Tuple[str, int, int]:
    """(texto con las fórmulas \\( … \\) convertidas, convertidas, dejadas en
    LaTeX). Lo que no se pudo convertir queda idéntico, con sus \\( y \\)."""
    cuenta = [0, 0]

    def cambia(m: "re.Match[str]") -> str:
        convertida = latex_a_texto(m.group(1))
        if convertida is None or not convertida:
            cuenta[1] += 1
            return m.group(0)
        cuenta[0] += 1
        return convertida

    return _FORMULA.sub(cambia, texto or ""), cuenta[0], cuenta[1]


def simbolos_usados() -> List[str]:
    """Todos los caracteres que esta conversión puede escribir (para la prueba
    contra la fuente)."""
    s = set("".join(_SIMBOLOS.values())) | set(_SUPER.values()) | set(_SUB.values())
    s |= set(_PIZARRA.values()) | set("∛∜√") | set(_FRACCIONES.values())
    return sorted(s)
