pass

def checkValues(parser, input, values):
    parser.parse(input)
    for value in values:
        if len(value) == 3:
            domain, i, v = value
            getter = lambda x: x
        elif len(value) == 4:
            domain, i, getter, v = value
            if isinstance(getter, str):
                attr = getter
                getter = lambda x: getattr(x, attr)
        if i is None:
            i = domain
            domain = "equitable"
        item = getattr(parser, domain)[i]
        got = getter(item)
        assert got == v, f"Expected {v}, got {got}"
