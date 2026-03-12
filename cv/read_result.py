import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.txt")
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        print(line, end="")
