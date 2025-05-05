import typing
import json
import datetime
from pytex import serialization
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


class Parser:
    """
    The parser is the main class that processes the input and executes the commands.
    """
    def __init__(self):
        self.state = state.State()
        self.builtin = {}
        # for now, characters and spaces are collected in a string
        for name, mod in ModuleManager.items():
            mod.populate(self)
        # now we are at a similar stage to INITEX. We do not need to keep the current state.
        # clear the dump state.
        self.state.dump()
        self.input = lexer.InputStack()
        # the stack of if levels. Each element is a tuple containing the conditional 
        # command and its position in the input.
        self.ifstack = []
        # the list stack
        self.lists = [vmode.VList(self, inner=False)]
        self.log = self.getLogFile()
        # the dumper instance variable should point to a function that takes the content of 
        # a dump file and writes it to a file. The \dump command (vmode.Dump) handles the 
        # dump and uses this variable. Here is an example of setting it.
        # def dumper:
        #     with open("dump.fmt", "w") as format:
        #         format.write(content)
        # parser.dumper = dumper
        self.dumper = None
        # tracing settings
        self.state.domains["tracing"].values.attach(self)
        # the builtin commands
    
    def getLogFile(self):
        """
        get the log file
        @return: the log file
        """
        self.logfile = resolver.InMemoryTextFile("")
        return self.logfile.open(for_read=False)

    def logContent(self):
        """
        return the content of the log file
        """
        if self.log.closed:
            return self.logfile.content
        return self.log.getvalue()

    def message(self, message: str, console: bool = True):
        """
        write a message to the log file and the console
        @param message: the message
        @param console: whether to write to the console
        """
        self.log.write(message + "\n")
        if console:
            print(message)
    
    def token(self):
        """
        get the next token from the input stack
        @return: the next token
        """
        t = self.input.read()
        if t is None:
            return None
        if t.is_command:
            if t.noexpand:
                t.noexpand = False
                t.definition = token.relax
            else:
                t.definition = self.lookup(t.name)
        return t
    
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
            if t is not None and t.is_command:
                definition = t.definition
                if definition is None:
                    raise ValueError("undefined command" + t.name, self.input.position())
                elif definition.expand is not None:
                    if self.tracingcommands:
                        self.trace(t, mode="expand")
                    definition.expand(self)
                    continue
            return t


    def parse(self, input, name: typing.Optional[str] = None):
        """
        parse the input
        @param input: the input
        @param name: the name of the input
        """
        # we first set up today etc.
        date = datetime.datetime.now()
        self.state.volatile["year"] = date.year
        self.state.volatile["month"] = date.month
        self.state.volatile["day"] = date.day
        self.state.volatile["time"] = date.hour * 60 + date.minute
        self.readFrom(input, name)
        self.run = True
        self.loop()
        if len(self.ifstack) > 0:
            raise ValueError("missing \\fi")
        
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
            t.execute(self)

    def readFrom(self, input, name: typing.Optional[str] = None):
        """
        read from the input
        @param input: the input
        """
        if isinstance(input, str):
            self.input.push(lexer.StringScanner(self.state, input, name))
        else:
            self.input.push(lexer.Scanner(self.state, input, name))

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
        while True:
            t = self.token_expand() if expand else self.token()
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
            self.newParagraph()
        if self.lists[-1].type == lists.LISTTYPE.HORIZONTAL:
            # The most common commands of all are the character commands that tell 
            # TeX to append a character to the current horizontal list, using the
            # current font. If two or more commands of this type occur in succession,
            # TeX processes them all as a unit, converting to ligatures and/or 
            # inserting kerns as directed by the font information. (Ligatures and 
            # kerns may be influenced by invisible “boundary” characters at the left 
            # and right, unless \noboundary appears.) Each character command adjusts
            # \spacefactor, using the \sfcode table as described in Chapter 12. 
            # In unrestricted horizontal mode, a ‘\discretionary{}{}{}’ item is 
            # appended after a character whose code is the \hyphenchar of its font, 
            # or after a ligature formed from a sequence that ends with such a 
            # character.
            f = self.state.parameters["currentfont"]
            hlist = self.lists[-1]
            hlist.append(f[c])
            sf = self.state.sfcode[ord(c)]
            if sf != 0:
                cf = self.state.globals["spacefactor"]
                if cf < 1000 < sf:
                    sf = 1000
                self.state.globals["spacefactor"] = sf
        else:
            # math mode.
            code = self.state.mathcode[ord(c)]
            # code 0x8000 is a special case, making the character active
            if code == 0x8000:
                token.ActiveToken(c).execute(self)
            else:
                char = self.mathChar(code)
                self.lists[-1].append(char)

    def mathChar(self, code):
            """
            create a math character
            @param code: the math code
            @return: the an atom with the symbol as the nucleus
            """
            fam = self.state.parameters["fam"]
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
        f = self.state.globals["spacefactor"]
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
        xspaceskip = self.state.parameters["xspaceskip"]
        spaceskip = self.state.parameters["spaceskip"]
        if f >= 2000 and xspaceskip.dimen != 0:
            spaceglue = xspaceskip
        elif spaceskip.dimen != 0:
            spaceglue = spaceskip.scale(f/1000)
        else:
            font = self.state.parameters["currentfont"]
            if f >= 2000:
                spaceglue = font.spaceglue.copy()
                spaceglue.dimen += font.param[6] # \fontdimen[7] is the extra space
            else:
                spaceglue = font.spaceglue
            spaceglue = spaceglue.scale(f/1000)
        top.append(node.Glue(spaceglue))

    def lookup(self, name):
        """
        look up a command
        @param name: the name of the command
        @return: the command
        """
        try:
            return self.state.equitable[name]
        except KeyError:
            return None

    def beginGroup(self, position, group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE, callback=None):
        """
        begin a group
        @param position: the position of the begin group token
        @param group_type: the type of the group
        @param callback: the callback function
        """
        # if we are already in math mode, then we are reading a subformula
        if self.lists[-1].type == lists.LISTTYPE.MATH:
            mlist = mmode.MList(self)
            self.lists[-1].append(mmode.Subformula(mlist))
            self.lists.append(mlist)
        self.state.beginGroup(position, group_type, callback)
    
    def endGroup(self, position, group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE):
        """
        end a group
        @param position: the position of the end group token
        @param group_type: the type of the group
        """
        self.state.endGroup(position, group_type)
        if self.lists[-1].type == lists.LISTTYPE.MATH:
            # check if we are building a general fraction
            if self.lists[-1].fraction is not None:
                den = self.lists.pop()
                fraction = den.fraction
                den.fraction = None
                num, _, bar, thickness = fraction.nucleus
                fraction.nucleus = (mmode.Subformula(num), mmode.Subformula(den), bar, thickness)
            # now, on the list stack, we are either in a subformula, or an equation number,
            # or the base math list started by a math shift. In the first two cases, we pop
            # off the list as we do not need them
            enclosing = self.lists[-2]
            if enclosing.type == lists.LISTTYPE.MATH:
                # this is a subformula. pop it.
                self.lists.pop()
        aftergroup = self.state.domains["globals"]["aftergroup"]
        if len(aftergroup) > 0:
            self.input.push(lexer.TokenListScanner(aftergroup))
            self.state.domains["globals"]["aftergroup"] = []

    def newHList(self):
        """
        create a new restricted horizontal list
        """
        return hmode.HList(self, True)
    
    def newVList(self):
        """
        create a new vertical list
        """
        return vmode.VList(self)
    
    def newIndentBox(self):
        """
        create a new indent box
        """
        return hmode.IndentBox(self)

    def newParagraph(self, indent: bool = True):
        """
        start a new paragraph: starting the horizontal list with an empty 
        # hbox whose width is \parindent. The \everypar tokens are inserted into 
        # TeX’s input. The page builder is exercised. When the paragraph is 
        # eventually completed, horizontal mode will come to an end as described 
        # in Chapter 25. (The TeX Book pp.282)        """
        hlist = paragraph.Paragraph(self, indent)
        self.lists.append(hlist)
        everypar = self.state.parameters["everypar"]
        if len(everypar) > 0:
            self.input.push(lexer.TokenListScanner(everypar))
        # the spacefactor is set to 1000 at the beginning of a paragraph
        self.state.globals["spacefactor"] = 1000
        return hlist

    def endParagraph(self):
        """
        end a paragraph
        """
        hlist = self.lists[-1]
        if hlist.type != lists.LISTTYPE.HORIZONTAL or hlist.inner:
            raise ValueError("cannot end the paragraph here", self.input.pos)
        # \unskip
        if len(hlist) > 0 and hlist[-1].node_type == node.NODE_TYPE.GLUE:
            hlist.pop()
        # \penalty10000
        hlist.append(node.Penalty(10000))
        # \hskip\parfillskip
        hlist.append(node.Glue(self.state.parameters["parfillskip"]))
        self.lists.pop()
        self.lists[-1].append(hlist)

    def hyphenChar(self):
        """
        get the hyphen character
        """
        font = self.state.parameters["currentfont"]
        c = font.fontchar["hyphenchar"]
        return self.state.parameters["defaulthyphenchar"] if c == 0 else c

    def dump(self) -> str:
        """
        dump the state as a format (JSON) file
        @return: the format file content
        """
        dump = serialization.serialize(self.state.dump())
        return json.dumps(dump)

    def load(self, file):
        """
        load the state from a format file
        @param file: the file to load the state
        """
        format = json.loads(file.read())
        self.state.load(serialization.deserialize(self, format))

    def end(self):
        """
        end the parser, and return the log
        """
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
        # \vfill\penalty-'10000000000
        top.append(node.Glue(glue.Glue(0, glue.Stretchness(1, 2))))
        top.append(node.Penalty(-0x100000))
        self.input.pop(to=self.input.top)
        self.run = False
        if not self.log.closed:
            self.log.close()
        return self.logContent()
