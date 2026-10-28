"""Write an OpenFOAM dictionary."""
import os


def vec(p):
    return "(%s)" % " ".join("%.6f" % float(x) for x in p)


def foam(class_, object_, body):
    text = body if body.endswith("\n") else body + "\n"
    return (
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       %s;\n"
        "    object      %s;\n"
        "}\n\n%s" % (class_, object_, text)
    )


def write(path, body, class_="dictionary"):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(foam(class_, os.path.basename(path), body))
