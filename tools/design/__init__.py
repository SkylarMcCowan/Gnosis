"""design.* tools: Gnosis's connection to a self-hosted Penpot instance
(https://penpot.app), so a model can build out a real design - projects,
files, boards, shapes - instead of only describing what one should look
like. Each wraps a function from penpot.py (this package never imports
webagent.py or penpot.py directly, same DI discipline as every other
tools/ subpackage - see tools/base.py's "HOW TO ADD A NEW TOOL").

design.list_projects/create_project/list_files/create_file/get_file
(list_projects.py/create_project.py/list_files.py/create_file.py/
get_file.py) cover project/file setup, scoped to the connected account's
single default team - Gnosis is single-user, so there's no team selection
to expose (see MEMORY: "Gnosis architecture"). design.add_board/add_shape
(add_board.py/add_shape.py) are what actually let a model draw something:
a board (frame) to lay a design out on, and a rect/circle/text shape
inside it or directly on the page.
"""
