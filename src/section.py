from .variable import *
from collections import OrderedDict

sections = ['info', 'config', 'variables', 'script', 'file', 'require']


class SectionFactory:
    varPattern = "([a-zA-Z0-9:]+)[=]([a-zA-Z0-9./]+)"
    namePattern = re.compile("^(?P<tags>[a-zA-Z0-9,]+[:])?(?P<name>info|config|variables|file (?P<fileName>[a-zA-Z0-9]+)|require|script(:?[@](?P<scriptRole>[a-zA-Z0-9]+))?)(?P<params>([ \t]"+varPattern+")+)?$")


    @staticmethod
    def build(testie, data):
        """
        Create a section from a given header
        :param testie: The parent script
        :param data: Array containing the section name and possible arguments
        :return: A Section object
        """
        matcher = SectionFactory.namePattern.match(data)
        if not matcher:
            raise Exception("Unknown section line %s" % data)

        if matcher.group('tags') is not None:
            tags = matcher.group('tags').split(',')
        else:
            tags=[]

        for tag in tags:
            if not tag in testie.tags:
                return SectionNull()

        sectionName = matcher.group('name')


        if (sectionName.startswith('script')):
            params = matcher.group('params')
            params = dict(re.findall(SectionFactory.varPattern,params)) if params else {}
            s = SectionScript(matcher.group('scriptRole'),params)
            return s

        if matcher.group('params') is not None:
            raise Exception("Only script sections takes arguments (" + sectionName + " has argument " + matcher.groups('params') + ")");

        if (sectionName.startswith('file')):
            s = SectionFile(matcher.group('fileName').strip())
            return s

        if hasattr(testie, sectionName):
            raise Exception("Only one section of type " + sectionName + " is allowed")

        if sectionName == 'variables':
            s = SectionVariable()
        elif sectionName == 'config':
            s = SectionConfig()
        elif sectionName == 'require':
            s = SectionRequire()
        elif sectionName == 'info':
            s = Section(sectionName)
        setattr(testie, s.name, s)
        return s


class Section:
    def __init__(self, name):
        self.name = name
        self.content = ''

    def finish(self, testie):
        pass

class SectionNull(Section):
    def __init__(self):
        self.content = ''



class SectionScript(Section):
    def __init__(self, role=None, params={}):
        self.name = 'script'
        self.content = ''
        self.params = params
        self._role = role

    def get_role(self):
        return self._role

    def finish(self, script):
        script.scripts.append(self)

    def delay(self):
        return float(self.params.get("delay",0))


class SectionFile(Section):
    def __init__(self, filename):
        self.name = 'file'
        self.content = ''
        self.filename = filename

    def finish(self, testie):
        testie.files.append(self)

class SectionRequire(Section):
    def __init__(self):
        self.name = 'require'
        self.content = ''

    def role(self):
        #For now, require is only on one node, the default one
        return 'default'

    def finish(self, testie):
        pass

class BruteVariableExpander:
    """Expand all variables building the full
    matrix first."""

    def __init__(self, vlist):
        self.expanded = [OrderedDict()]
        for k, v in vlist.items():
            newList = []
            for nvalue in v.makeValues():
                for ovalue in self.expanded:
                    z = ovalue.copy()
                    z.update({k: nvalue})
                    newList.append(z)
            self.expanded = newList
        self.it = self.expanded.__iter__()

    def __next__(self):
        return self.it.__next__()


class SectionVariable(Section):
    def __init__(self):
        self.name = 'variables'
        self.content = ''
        self.vlist = OrderedDict()

    def replace_all(self, value):
        """Return a list of all possible replacement in values for each combination of variables"""
        statics = self.statics()
        if len(statics):
            pattern = re.compile("\$(" + "|".join(statics.keys()) + ")")
            value = pattern.sub(lambda m: statics[re.escape(m.group(0))], value)

        dynamics = self.dynamics()
        pattern = re.compile("\$(" + "|".join(dynamics.keys()) + ")")
        values = []
        for variables in BruteVariableExpander(dynamics).it:
            nvalue = pattern.sub(lambda m: str(variables[re.escape(m.group(1))]), value)
            values.append(nvalue)
        return values

    def __iter__(self):
        return BruteVariableExpander(self.vlist)

    def dynamics(self):
        """List of non-constants variables"""
        dyn = OrderedDict()
        for k, v in self.vlist.items():
            if v.count() > 1: dyn[k] = v
        return dyn

    def is_numeric(self, k):
        v = self.vlist.get(k,None)
        if v is None:
            return True
        return v.is_numeric()

    def statics(self):
        """List of constants variables"""
        dyn = OrderedDict()
        for k, v in self.vlist.items():
            if v.count() <= 1: dyn[k] = v
        return dyn

    def override_all(self, dict):
        for k,v in dict.items():
            self.override(k,v)

    def override(self, var, val):
        if isinstance(val, Variable) :
            self.vlist[var] = val
        else:
            self.vlist[var] = SimpleVariable(var,val)

    def parse_variable(self, line, tags):
        try:
            if not line:
                return None,None
            pair = line.split('=', 1)
            var = pair[0].split(':')

            if len(var) == 1:
                var = var[0]
            else:
                if (var[0] in tags) or (var[0].startswith('-') and not var[0][1:] in tags):
                    var = var[1]
                else:
                    return None,None
            return var,VariableFactory.build(var, pair[1], self)
        except:
            print("Error parsing line %s" % line)
            raise

    def finish(self, testie):
        for line in self.content.split("\n"):
            var,val = self.parse_variable(line,testie.tags)
            if not var is None:
                self.vlist[var] = val
        self.vlist = OrderedDict(sorted(self.vlist.items()))

    def dtype(self):
        formats=[]
        names=[]
        for k, v in self.vlist.items():
            f = v.format()
            formats.append(f)
            names.append(k)
        return dict(names = names, formats = formats)


class SectionConfig(SectionVariable):
    def __add(self, var, val):
        self.vlist[var] = SimpleVariable(var, val)

    def __add_list(self, var, list):
        self.vlist[var] = ListVariable(var, list)

    def __add_dict(self, var, dict):
        self.vlist[var] = DictVariable(var, dict)

    def __init__(self):
        self.name = 'config'
        self.content = ''
        self.vlist = {}
        self.__add("accept_outliers_mult", 1)
        self.__add("accept_variance", 1)
        self.__add("timeout", 30)
        self.__add("acceptable", 0.01)
        self.__add("n_runs", 3)
        self.__add("n_retry", 0)
        self.__add("zero_is_error", True)
        self.__add("n_supplementary_runs", 3)
        self.__add_dict("var_names", {})
        self.__add_dict("var_unit", {"result": "BPS"})
        self.__add("legend_loc", "best")
        self.__add("var_hide", {})
        self.__add("var_log", [])
        self.__add("autokill", True)
        self.__add_list("require_tags", [])

    def var_name(self, key):
        if key in self["var_names"]:
            return self["var_names"][key]
        else:
            return key

    def get_list(self,key):
        var = self.vlist[key]
        v = var.makeValues()
        return v

    def get_dict(self,key):
        var = self.vlist[key]
        try:
            v = var.vdict
        except AttributeError:
            print("WARNING : Error in configuration of %s" % key)
            return {key:var.makeValues()[0]}
        return v

    def __contains__(self, key):
        return key in self.vlist

    def __getitem__(self, key):
        var = self.vlist[key]
        v = var.makeValues()
        if type(v) is list and len(v) == 1:
            return v[0]
        else:
            return v

    def __setitem__(self, key, val):
        self.__add(key, val)


    def finish(self, testie):
        super().finish(testie)
        # for k,v in self.vlist.items():
        #     print("config %s is %s" %(k,v.makeValues()))
        #     print("config %s is %s" % (k, self.get_list(k)))
