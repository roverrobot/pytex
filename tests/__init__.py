pass

def checkValues(parser, input, values):
    parser.parse(input)
    for value in values:
        domain, i, v = value
        assert parser.state.domains[domain][i] == v
