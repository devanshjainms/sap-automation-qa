from agent_framework_orchestrations import SequentialBuilder
class S:
    def run(self): pass
w = SequentialBuilder(participants=[S()]).build()
import sys
help(type(w))
