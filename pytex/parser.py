import typing
import datetime
from fractions import Fraction
from pytex import serialization
from pytex import formatfile
from pytex import token
from pytex import lexer
from pytex import state
from pytex.module import ModuleManager
from pytex import accessor
from pytex import integer
from pytex import keyword
from pytex import dimen
from pytex import glue
from pytex import arithmatic
from pytex import define
from pytex import toks
from pytex import macro
from pytex import conditional
from pytex import expandable
from pytex import resolver
from pytex import node
from pytex import font
from pytex import lists
from pytex import vmode
from pytex import hmode
from pytex import box
from pytex import file
from pytex import mmode
from pytex import paragraph
from pytex import align
from pytex import hyphen
from pytex import misc
from pytex import tracing
from pytex import page
import os


class Parser:
    """
    The parser is the main class that processes the input and executes the commands.
    """
    def __init__(self, project_dir: typing.Optional[str] = None):
        self.initState()
        # the builtin commands
        self.builtin = {}
        # now we are at a similar stage to INITEX. We do not need to keep the current state.
        self.input = lexer.InputStack()
        self.token = self.input.read
        # the stack of if levels. Each element is a tuple containing the conditional 
        # command and its position in the input.
        self.ifstack = []
        self.lists = None
        self.jobname = "texput"
        self.log = None
        self.log_path = None
        # the console file. None to standard output, or os.devnull for no output
        self.console = None
        # the dumper instance variable should point to a function that takes the content of
        # a binary format file and writes it to a file. The \dump command (vmode.Dump) handles the
        # dump and uses this variable. Here is an example of setting it.
        # def dumper:
        #     with open("dump.pfmt", "wb") as format:
        #         format.write(content)
        # parser.dumper = dumper
        self.dumper = None
        # for now, characters and spaces are collected in a string
        for name, mod in ModuleManager.items():
            mod.populate(self)
        self.value_readers = [None] * (max(accessor.VALUE_TYPE) + 1)
        self.value_readers[accessor.VALUE_TYPE.INT] = self.readInteger
        self.value_readers[accessor.VALUE_TYPE.DIMEN] = self.readDimen
        self.value_readers[accessor.VALUE_TYPE.GLUE] = self.readGlue
        self.value_readers[accessor.VALUE_TYPE.MUGLUE] = lambda: self.readGlue(mu=True)
        self.value_readers[accessor.VALUE_TYPE.BOX] = self.readBox
        self.value_readers[accessor.VALUE_TYPE.TOKS] = lambda: toks.readToks(self)
        self.value_readers[accessor.VALUE_TYPE.FONT] = lambda: font.readFont(self)
        if isinstance(getattr(self, "resolver", None), resolver.FileResolver):
            self.resolver = self.resolver.clone(project_dir=project_dir)
        # the current command token
        self.current_token = None
        self.lastbox = None
        self.ended = False
        self.formatfile = None

    def initState(self):
        self.groups = []
        self.current_group = None
        self.globals = state.Globals()
        self.volatile = state.Dict("volatile", self)
        self.parameters = state.Dict("parameters", self)
        self.equitable = state.Dict("equitable", self)
        self.layout = state.Dict("layout", self)
        self.arrays = {}

    def dumpState(self):
        """
        dump the parser-owned grouped state
        @return: a dict that represents the state
        """
        data = {
            "equitable": self.equitable.dump(),
            "parameters": self.parameters.dump(),
            "layout": self.layout.dump(),
        }
        for name, array in self.arrays.items():
            data[name] = array.dump()
        return data

    def loadState(self, data):
        """
        restore the parser-owned grouped state
        @param data: a previously dumped data
        """
        self.equitable.load(data.get("equitable", {}))
        self.parameters.load(data.get("parameters", {}))
        self.layout.load(data.get("layout", {}))
        for name, array in self.arrays.items():
            if name in data:
                array.load(data[name])

    def remove(self, domain: state.Domain, index):
        """
        remove a value from all active groups
        @param domain: the domain of the value
        @param index: the index of the value
        """
        if self.current_group:
            self.current_group.remove(domain, index)
            for group in self.groups:
                group.remove(domain, index)

    def readTarget(self):
        """
        read an assignment target and return a bound target
        @param meaning: optional accessor-like object; if omitted it is read from input
        @return: the resolved target
        """
        t = self.token_expand()
        if t is None:
            return None
        if t.definition is None or getattr(t.definition, "getTarget", None) is None:
            self.input.unread(t)
            return None
        meaning = t.definition
        if getattr(meaning, "getTarget", None) is None:
            self.input.unread(t)
            return None
        return meaning.getTarget(self)

    def get(self, target):
        """
        get a value from a bound target
        @param target: the bound target
        @return: the retrieved value
        """
        return target.get()

    def cast(self, value, value_type):
        """
        cast a value to a new type
        @param value: the source value
        @param value_type: the desired VALUE_TYPE
        @return: the casted value, or None if the cast is unsupported
        """
        if value is None:
            return None
        if value_type == accessor.VALUE_TYPE.INT:
            if isinstance(value, int):
                return value
            if isinstance(value, dimen.Dimen):
                return int(value)
            if isinstance(value, (glue.Glue, glue.MuGlue)):
                return int(value.dimen)
            return None
        if value_type == accessor.VALUE_TYPE.DIMEN:
            if isinstance(value, dimen.Dimen):
                return value
            if isinstance(value, (glue.Glue, glue.MuGlue)):
                return value.dimen
            return None
        if value_type == accessor.VALUE_TYPE.GLUE:
            if isinstance(value, glue.Glue):
                return value
            return None
        if value_type == accessor.VALUE_TYPE.MUGLUE:
            if isinstance(value, glue.MuGlue):
                return value
            return None
        if value_type in {
            accessor.VALUE_TYPE.TOKS,
            accessor.VALUE_TYPE.FONT,
            accessor.VALUE_TYPE.MEANING,
        }:
            return value
        return value if value_type == accessor.VALUE_TYPE.UNKNOWN else None

    def readValue(self, value_type):
        """
        Read a value according to the requested VALUE_TYPE.
        """
        if value_type == accessor.VALUE_TYPE.UNKNOWN:
            raise NotImplementedError("readValue requires a concrete value type")
        reader = self.value_readers[value_type]
        if reader is None:
            raise NotImplementedError(f"no reader registered for value type {value_type}")
        return reader()

    def readInternalValue(self, value_type, expand: bool = True):
        """
        Read an internal value of the requested type from the next token.

        @param value_type: the expected VALUE_TYPE
        @param expand: whether to expand the token before checking its meaning

        If the next token does not denote an internal value of that shape, it is
        unread and `None` is returned.
        """
        t = self.token_expand() if expand else self.token()
        if t is None:
            return None
        meaning = t.definition
        getter_name = {
            accessor.VALUE_TYPE.MEANING: "meaningValue",
        }.get(value_type)
        value = None
        get_target = getattr(meaning, "getTarget", None)
        can_bind = False
        if get_target is not None:
            if isinstance(meaning, accessor.Accessor):
                compatible_targets = {
                    accessor.VALUE_TYPE.INT: {accessor.VALUE_TYPE.INT},
                    accessor.VALUE_TYPE.DIMEN: {accessor.VALUE_TYPE.INT, accessor.VALUE_TYPE.DIMEN},
                    accessor.VALUE_TYPE.GLUE: {
                        accessor.VALUE_TYPE.INT,
                        accessor.VALUE_TYPE.DIMEN,
                        accessor.VALUE_TYPE.GLUE,
                    },
                    accessor.VALUE_TYPE.MUGLUE: {
                        accessor.VALUE_TYPE.INT,
                        accessor.VALUE_TYPE.DIMEN,
                        accessor.VALUE_TYPE.MUGLUE,
                    },
                    accessor.VALUE_TYPE.TOKS: {accessor.VALUE_TYPE.TOKS},
                    accessor.VALUE_TYPE.FONT: {accessor.VALUE_TYPE.FONT},
                    accessor.VALUE_TYPE.MEANING: {accessor.VALUE_TYPE.MEANING},
                }
                can_bind = (
                    meaning.canBindInternalValue()
                    and value_type in compatible_targets.get(meaning.target_type, set())
                )
            else:
                can_bind = True
        if can_bind:
            target = get_target(self)
            if getattr(target, "readable", True):
                try:
                    value = self.cast(self.get(target), value_type)
                except (IndexError, KeyError, TypeError):
                    value = None
        elif getter_name is not None:
            getter = getattr(meaning, getter_name, None)
            if getter is not None:
                value = getter(self)
        if value is not None:
            return value
        self.input.unread(t)
        return None

    def resolveGlobalScope(self, global_scope: bool = False):
        """
        resolve the final global scope for an assignment-like write
        @param global_scope: the requested global scope from prefixes or callers
        @return: the effective global scope after applying \\globaldefs
        """
        globaldefs = self.parameters["globaldefs"]
        if globaldefs > 0:
            return True
        if globaldefs < 0:
            return False
        return global_scope

    def set(self, target, value, *, global_scope: bool = False):
        """
        set a bound target
        @param target: the bound target
        @param value: the value to write
        @param global_scope: whether to write globally instead of locally
        @return: the written value
        """
        return target.set(value, global_scope=global_scope)

    def afterAssignment(self):
        """
        schedule the pending \\afterassignment token, if any
        """
        t = self.globals["afterassignment"]
        if t is None:
            return None
        self.input.unread(t)
        self.globals["afterassignment"] = None
        if self.tracingcommands > 0 and self.checkRange():
            self.message(f"afterassignment: {self.tokenToString(t)}")
        return t

    def logFileName(self):
        """
        Get the log file path in the current working directory.
        """
        name = os.path.basename(os.fspath(self.jobname if self.jobname else "texput"))
        if not name.endswith(".log"):
            name += ".log"
        return name

    def getLogFile(self):
        """
        Open the log file if needed.
        """
        path = self.logFileName()
        if self.log is not None and not self.log.closed:
            if self.log_path == path:
                return self.log
            if self.log.tell() != 0:
                return self.log
            self.log.close()
            if self.log_path and os.path.exists(self.log_path):
                os.remove(self.log_path)
        self.log_path = path
        self.log = open(path, "w")
        return self.log

    def logContent(self):
        """
        return the content of the log file
        """
        if self.log is not None and not self.log.closed:
            self.log.flush()
        if self.log_path is None or not os.path.exists(self.log_path):
            return ""
        with open(self.log_path, "r") as log:
            return log.read()

    def message(self, message: str, console: bool = True):
        """
        write a message to the log file and the console
        @param message: the message
        @param console: whether to write to the console
        """
        self.getLogFile()
        print(message, file=self.log)
        if console:
            print(message, file=self.console)
    
    def token_expand(self):
        """
        get the next token from the input stack and expand it
        @param protected: whether the protected tokens are prevented from expansion
        @return: the next token
        """
        while True:
            t = self.token()
            # t is expanable. As a token, it is either a command sequence or an active token
            # if its meaning is None, we find its meaning by expanding it
            if t is not None and t.entry is not None:
                definition = t.definition
                if definition is None:
                    raise ValueError("undefined command" + t.name, self.input.position())
                if definition.expand is not None:
                    if self.tracingcommands:
                        self.trace(t, mode="expand")
                    self.current_token = t
                    t = definition.expand(self)
                    if t is None:
                        continue
            return t

    def token_meaning(self, t):
        """
        resolve a \\let alias to a literal token without expanding commands.
        This is used by syntax scanners that accept things like \\bgroup.
        """
        if t is not None and t.entry is not None and isinstance(t.definition, token.Token):
            return t.definition
        return t

    def parse(self, input, jobname: typing.Optional[str] = None):
        """
        parse the input
        @param input: the input
        @param name: the name of the input
        """
        # we first set up today etc.
        if self.lists is None:
            self.lists = lists.ListStack([page.MainVList(self)])
        date = datetime.datetime.now()
        self.volatile["year"] = date.year
        self.volatile["month"] = date.month
        self.volatile["day"] = date.day
        self.volatile["time"] = date.hour * 60 + date.minute
        self.readFrom(input, jobname)
        if jobname is not None:
            base = os.path.basename(jobname)
            self.jobname = os.path.splitext(base)[0]
        self.getLogFile()
        self.run = True
        self.loop()
        self.run = False
        if len(self.ifstack) > 0:
            raise ValueError(f"missing \\fi for {self.ifstack[-1][0].name} at {self.ifstack[-1][1]}")
        
    def close(self):
        self.input.clear()
        shipout = getattr(self, "shipout", None)
        if shipout is not None:
            shipout.close()
        if self.log is not None and not self.log.closed:
            self.log.close()
        
    def loop(self):
        """
        the main read-execute loop
        """
        while self.run:
            t = self.token_expand()
            if t is None:
                self.run = False
                break
            if self.tracingcommands:
                self.trace(t, mode="execute")
            self.current_token = t
            t.execute(self)

    def readFrom(self, input, name: typing.Optional[str] = None):
        """
        read from the input
        @param input: the input
        """
        if isinstance(input, str):
            self.input.push(lexer.StringScanner(self, input, name))
        else:
            self.input.push(lexer.Scanner(self, input, name))

    def skipSpace(self, expand: bool = True):
        """
        skip one optional space
        @param expand: whether to expand tokens
        """
        t = self.token_expand() if expand else self.token()
        if t is not None and not t.isSpace(expand):
            self.input.unread(t)

    def skipSpaces(self, expand: bool = True):
        """
        skip spaces
        @param expand: whether to expand tokens
        @return the next nonspace token
        """
        tok = self.token_expand if expand else self.token
        while True:
            t = tok()
            if t is None or not t.isSpace(expand):
                return t

    def addChar(self, c):
        """
        add a character to the current list
        @param c: the character token
        """
        if self.lists[-1].type == lists.LISTTYPE.VERTICAL:
            # if any of these tokens occurs as a command in vertical mode or 
            # internal vertical mode, TeX automatically performs an \indent 
            # command as explained above. This leads into horizontal mode with 
            # the \everypar tokens in the input, after which TeX will see the 
            # horizontal command again. The TeX Book pp.283
            if self.current_token is not None:
                self.input.unread(self.current_token)
            self.newParagraph()
            return
        if self.lists[-1].type == lists.LISTTYPE.HORIZONTAL:
            # The most common commands of all are the character commands that tell 
            # TeX to append a character to the current horizontal list, using the
            # current font. If two or more commands of this type occur in succession,
            # TeX processes them all as a unit, converting to ligatures and/or
            # inserting kerns as directed by the font information. In this lazy
            # model we keep the raw character nodes here, and defer that ligature/
            # kern processing until the horizontal list is typeset. Each character
            # command adjusts
            # \spacefactor, using the \sfcode table as described in Chapter 12. 
            # In unrestricted horizontal mode, a ‘\discretionary{}{}{}’ item is 
            # appended after a character whose code is the \hyphenchar of its font, 
            # or after a ligature formed from a sequence that ends with such a 
            # character.
            f = self.parameters["currentfont"]
            self.lists[-1].append(f[c])
        else:
            # math mode.
            code = self.mathcode[ord(c)]
            # code 0x8000 is a special case, making the character active
            if code == 0x8000:
                t = token.ActiveToken(c)
                t.entry = self.equitable.entry(c)
                # Requeue as a command token so it goes through normal
                # token_expand/execute handling (expandable and non-expandable).
                self.input.unread(t)
            else:
                char = self.mathChar(code)
                self.lists[-1].append(char)

    def mathChar(self, code):
            """
            create a math character
            @param code: the math code
            @return: the an atom with the symbol as the nucleus
            """
            fam = self.parameters["fam"]
            return mmode.MathSymbol(code, fam)

    def addSpace(self):
        """
        add a space to the current list
        @param c: the token representing space
        """
        # Spaces have no eﬀect in vertical modes or math modes.
        top = self.lists[-1]
        type = top.type 
        if type == lists.LISTTYPE.VERTICAL or type == lists.LISTTYPE.MATH:
            return
        # In horizontal mode, a space token appends glue to the current list,
        # see the TeX Book pp.76 for more details.
        f = self.globals["spacefactor"]
        # If the space factor f is diﬀerent from 1000, the interword glue is 
        # computed as follows: Take the normal space glue for the current font, 
        # and add the extra space if f ≥ 2000. (Each font specifies a normal space, 
        # normal stretch, normal shrink, and extra space; for example, these 
        # quantities are 3.33333 pt, 1.66666 pt, 1.11111 pt, and 1.11111 pt, 
        # respectively, in cmr10. We’ll discuss such font parameters in greater
        # detail later.) Then the stretch component is multiplied by f/1000, while 
        # the shrink component is multiplied by 1000/f.
        # However, TeX has two parameters \spaceskip and \xspaceskip that allow
        # you to override the normal spacing of the current font. If f ≥2000 and 
        # if \xspaceskip is nonzero, the \xspaceskip glue is used for an interword 
        # space. Otherwise if \spaceskip is nonzero, the \spaceskip glue is used, 
        # with stretch and shrink components multiplied by f/1000 and 1000/f. For 
        # example, the \raggedright macro of plain TeX uses \spaceskip and 
        # \xspaceskip to suppress all stretching and shrinking of interword spaces.
        xspaceskip = self.parameters["xspaceskip"]
        spaceskip = self.parameters["spaceskip"]
        scale = Fraction(f, 1000)
        if f >= 2000 and xspaceskip.dimen != 0:
            spaceglue = xspaceskip
        elif spaceskip.dimen != 0:
            spaceglue = spaceskip.scale(scale)
        else:
            font = self.parameters["currentfont"]
            if f >= 2000:
                spaceglue = font.spaceglue.copy()
                spaceglue.dimen += font.param[6] # \fontdimen[7] is the extra space
            else:
                spaceglue = font.spaceglue
            spaceglue = spaceglue.scale(scale)
        top.append(node.Glue(spaceglue, None))

    def lookup(self, name):
        """
        look up a command
        @param name: the name of the command
        @return: the command
        """
        return self.equitable[name]

    def beginGroup(
        self,
        position,
        group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE,
        to_end=None,
        ended=None,
    ):
        """
        begin a group
        @param position: the position of the begin group token
        @param group_type: the type of the group
        @param to_end: callback before local values are restored, called as to_end(parser)
        @param ended: callback after group close, called as ended(parser)
        """
        # if we are already in math mode, then we are reading a subformula
        if group_type == state.GROUP_TYPE.SIMPLE and self.lists[-1].type == lists.LISTTYPE.MATH:
            subformula = mmode.Subformula()
            self.lists.append(mmode.MList(self, subformula.list))
            ended = mmode.MathEndGroupCallback(subformula)
        if self.current_group:
            self.groups.append(self.current_group)
        self.current_group = state.Group(position, group_type, to_end=to_end, ended=ended)
    
    def endGroup(self, position, group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE):
        """
        end a group
        @param position: the position of the end group token
        @param group_type: the type of the group
        """
        if not self.current_group:
            raise ValueError("no current group")
        group = self.current_group
        aftergroup = group.aftergroup
        to_end = group.to_end
        ended = group.ended
        if not group.match(group_type):
            raise ValueError(f"mismatched group type starting at {group.position} and ending at {position}")
        if to_end:
            to_end(self)
        group.end(position, group_type)
        if self.groups:
            self.current_group = self.groups.pop()
        else:
            self.current_group = None
        if ended:
            ended(self)
        if aftergroup:
            self.input.push(lexer.TokenListScanner(aftergroup))
            if self.tracingcommands > 0 and self.checkRange():
                self.message(f"aftergroup: {self.toksToString(aftergroup)}")

    def newIndentBox(self):
        """
        create a new indent box
        """
        return hmode.IndentBox(self)

    def newParagraph(
        self,
        indent: bool = True,
        parskip: bool = True,
    ):
        """
        start a new paragraph: starting the horizontal list with an empty 
        # hbox whose width is \\parindent. The \\everypar tokens are inserted into 
        # TeX’s input. The page builder is exercised. When the paragraph is 
        # eventually completed, horizontal mode will come to an end as described 
        # in Chapter 25. (The TeX Book pp.282)        """
        top = self.lists[-1]
        para = paragraph.Paragraph(self, indent)
        if parskip:
            parskip_node = node.Glue(self.parameters["parskip"], "\\parskip")
            parskip_node.source = para
            top.append(parskip_node)
        self.lists.append(paragraph.ParagraphList(self, para))
        if parskip:
            everypar = self.everypar.value
            if everypar:
                self.input.push(lexer.TokenListScanner(everypar))
                if self.tracingcommands > 0 and self.checkRange():
                    self.message(f"everypar: {self.toksToString(everypar)}")
            self.globals["prevgraf"] = 0
        return para

    def endParagraph(self):
        """
        End the current paragraph using TeX's primitive paragraph builder.
        """
        hlist = self.lists[-1]
        if hlist.type != lists.LISTTYPE.HORIZONTAL or hlist.inner:
            raise ValueError("cannot end the paragraph here", self.input.position())
        para = hlist.paragraph
        if para is None:
            raise ValueError("missing paragraph node", self.input.position())
        # \unskip
        self.lists.pop()
        if len(hlist) > 0 and hlist[-1].node_type == node.NODE_TYPE.GLUE:
            hlist.pop()
        top = self.lists[-1]
        # A truly empty paragraph contributes nothing (e.g., \noindent\par).
        # TeX does not emit a synthetic empty line in this case.
        updates_display_state = True
        if len(hlist) == 0:
            para = None
        else:
            # \penalty10000
            hlist.append(node.Penalty(10000))
            # \hskip\parfillskip
            hlist.append(node.Glue(self.parameters["parfillskip"], "\\parfillskip"))
            top.append(para)
        if para is not None:
            if updates_display_state:
                para.updateDisplayState(self)
        # TeX clears \\looseness etc after each paragraph.
        self.clearParagraphSettings()
        return para

    def clearParagraphSettings(self):
        volatile = self.volatile
        volatile["looseness"] = 0
        volatile["hangindent"] = dimen.Dimen()
        volatile["hangafter"] = 1
        volatile["parshape"] = []

    def hyphenChar(self):
        """
        get the hyphen character
        """
        font = self.parameters["currentfont"]
        c = font.fontchar["hyphenchar"]
        return self.parameters["defaulthyphenchar"] if c == 0 else c

    def dump(self) -> bytes:
        """
        Dump the state as a format container.
        @return: the format file content
        """
        return formatfile.dump(self)

    def load(self, file):
        """
        load the state from a format file
        @param file: the file to load the state
        """
        self.formatfile = None
        data = file.read()
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("format files must be opened in binary mode")
        if not formatfile.isContainer(data):
            raise ValueError("unsupported format file")
        formatfile.load(self, data)
        # Keep interaction-mode primitives distinct from \relax even when loading
        # older formats that serialized them as no-op relax aliases.
        for name in (
            "\\batchmode",
            "\\nonstopmode",
            "\\scrollmode",
            "\\errorstopmode",
        ):
            builtin = self.builtin.get(name)
            if builtin is not None:
                self.equitable.setGlobal(name, builtin)

    def end(self):
        """
        end the parser
        """
        if self.ended:
            return
        self.ended = True
        self.run = False
        top = self.lists[-1]
        if top.type == lists.LISTTYPE.HORIZONTAL:
            if top.inner:
                raise ValueError("end in internal horizontal mode")
            self.endParagraph()
        elif top.type == lists.LISTTYPE.MATH:
            raise ValueError("end in math mode")
        top = self.lists[-1]
        if top.type != lists.LISTTYPE.VERTICAL or top.inner:
            raise ValueError("did not end in the main vertical list")
        top.finish(self)
        self.shipout.close()

        
