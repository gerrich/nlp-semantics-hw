#!/usr/bin/python
################################################################################

from collections import defaultdict
import operator

import logic_ast_nodes as nodes

class SqlGenerator:
    SYMBOL_MAPPING = {
        "Likes" : 'my_likes',
        "Hates" : 'my_hates',
        "John"  : 'John',
        "Mary"  : 'Mary'
    }

    def __init__(self):
        self.type = None

        self.tables = list()
        self.variables = defaultdict(set)
        self.constraints = []

        self.stack = []

    def is_insert(self, node):
        return \
            isinstance(node, nodes.Application) or \
            isinstance(node, nodes.Negation) or \
            isinstance(node, nodes.And) or \
            isinstance(node, nodes.Or)

    def is_select(self, node):
        return \
            isinstance(node, nodes.Lambda)

    def resolve_column(self, table, n):
        return "arg%d" % n

    def resolve_table(self, table):
        if isinstance(table, str):
            return str
        elif isinstance(table, nodes.Symbol):
            n = self.SYMBOL_MAPPING[table.name]
            t = "alias%d_%s" % (len(self.tables), n)
            self.tables.append((n, t))
            return t
        else:
            raise RuntimeError, "Unable to deduce table name from value: {0}".format(repr(table))

    def resolve_value(self, value):
        if isinstance(value, str):
            return repr(value)
        elif isinstance(value, tuple):
            assert(len(value) >= 2)
            return "%s.%s" % (value[0], self.resolve_column(value[0], value[1]))
        elif isinstance(value, nodes.Symbol):
            return repr(value.name)
        else:
            raise RuntimeError, "Unable to deduce table name from value: {0}".format(repr(value))

    def _visit_function(self, node):
        if isinstance(node, nodes.Application):
            table, values = node.uncurry()

            table = self.resolve_table(table)

            for n, value in enumerate(values):
                if isinstance(value, nodes.Symbol):
                    self.constraints.append((table, n, value))
                elif isinstance(value, nodes.Variable):
                    self.variables[value.name].add((table, n))
        elif isinstance(node, nodes.And):
            node.visit(self._visit_function, self._visit_combinator, None)
        elif isinstance(node, nodes.Not):
            raise RuntimeError, "'Not' clauses are not supported currently."
        elif isinstance(node, nodes.Or):
            raise RuntimeError, "'Or' clauses are not supported currently."
        else:
            raise RuntimeError, "Unsupported node: {0}".format(repr(node))

    def _visit_combinator(self, *args):
        pass

    def _induce_variable_constraints(self):
        for variable in self.variables:
            variable_constraints = list(self.variables[variable])
            for lhs, rhs in zip(variable_constraints[0:], variable_constraints[1:]):
                self.constraints.append((lhs[0], lhs[1], rhs))

    def make_insert(self, node):
        self.type = "INSERT"
        
        func, args = node.uncurry()
        if str(func) == 'Count':
          generator = self.make_select(args[0], modifier = 'Count')
          for item in generator:
              yield item
        elif str(func) == 'Check':
          generator = self.make_select(nodes.Lambda(None, args[0]), modifier = 'Check')
          for item in generator:
              yield item
        else:
          self._visit_combinator(self._visit_function(node))

          original_table_names = set(map(operator.itemgetter(0), self.tables))
          mapped_table_names = set(map(operator.itemgetter(1), self.tables))

          if len(original_table_names) != len(mapped_table_names):
              raise RuntimeError, "Expression is too complex to be converted into a single insert statement."

          reverse_table_mapping = dict(map(lambda x: (x[1], x[0]), self.tables))

          inserted_values = defaultdict(list)

          for table, column, value in self.constraints:
              inserted_values[table].append( (self.resolve_column(table, column), self.resolve_value(value)) )
          for table in inserted_values.iterkeys():
              columns_and_values = inserted_values[table]

              columns = map(operator.itemgetter(0), columns_and_values)
              values = map(operator.itemgetter(1), columns_and_values)

              table_clause = "%s(%s)" % (reverse_table_mapping[table], ", ".join(columns))
              values_clause = "(%s)" % (", ".join(values))

              yield "INSERT INTO %s VALUES %s" % (table_clause, values_clause)

    def make_select(self, node, modifier = None):
        self.type = "SELECT"

        variables, body = node.uncurry()
        
        self._visit_combinator(self._visit_function(body))
        self._induce_variable_constraints()

        result_clause = ''
        if modifier == 'Count':
          result_clause = 'COUNT(*)'
        if modifier == 'Check':
          result_clause = 'CASE WHEN COUNT(*)!=0 THEN "YES" ELSE "NO" END'
        else:
            result_clause = ", ".join(map(
                lambda kv: "%s AS %s" % (self.resolve_value(list(kv[1])[0]), kv[0]),
                self.variables.items()))

        from_clause = ", ".join(map(
            lambda t: "%s AS %s" % t,
            self.tables))
        where_clause = " AND ".join(map(
            lambda c: "%s = %s" % (self.resolve_value(c[0:2]), self.resolve_value(c[2])), 
            self.constraints))
        query = "SELECT {0} FROM {1} WHERE {2}".format(result_clause, from_clause, where_clause)
        yield query

    def make_sql(self, node):
        generator = None

        if self.is_insert(node):
            generator = self.make_insert(node)
        elif self.is_select(node):
            generator = self.make_select(node)
        else:
            raise RuntimeError, "Unable to determine SQL query type; probably expression is too complex."

        for item in generator:
            yield item
