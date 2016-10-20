#!/usr/bin/env python
# encoding: utf-8

# from pprint import pprint as pp
from functools import partial, wraps
from itertools import ifilterfalse
from os import listdir
from operator import itemgetter
from jinja2 import Environment, FileSystemLoader
from slugify import slugify
import inflect
import os
import re
import argparse

p = inflect.engine()


def count_type(columns, type_):
    return len([c for c in columns if c['type']==type_])


def compose(*funcs):
    def bind(value, function):
        return function(value)

    """Return a new function s.t.
    compose(f,g,...)(x) == f(g(...(x)))"""

    def inner(data):
        return reduce(bind, reversed(funcs), data)

    return inner


def caster(casting_function):
    @wraps(casting_function)
    def inner(func):
        @wraps(func)
        def innest(*args, **kwargs):
            return casting_function(func(*args, **kwargs))

        return innest

    return inner


def funccaller(function_name, *args, **kwargs):
    def inner(object_):
        return getattr(object_, function_name)(*args, **kwargs)

    return inner


def safe_open(file_path, mode='w+'):
    os.system('mkdir -p "%s"' % (file_path.rpartition('/')[0]))
    return file(file_path, mode)


@caster(unicode)
def snake_to_spaced(snake):
    snake_care_pattern = re.compile(r'(?:_([a-z]+))')
    camel = snake_care_pattern.sub(lambda mo: ' ' + mo.group(1).title(), snake)
    return capitalize(camel)


@caster(unicode)
def snake_to_camel(snake):
    snake_care_pattern = re.compile(r'(?:_([a-z]+))')
    camel = snake_care_pattern.sub(lambda mo: mo.group(1).title(), snake)
    return camel


@caster(unicode)
def pluralize(string):
    plural = p.plural(string)
    return plural if plural else string


@caster(unicode)
def singularize(string):
    singular = p.singular_noun(string)
    return singular if singular else string


@caster(unicode)
def capitalize(string):
    return string[0].upper() + string[1:]


@caster(unicode)
def lower(string):
    return string[0].lower() + string[1:]


@caster(unicode)
def table_name_to_model_name(table_name):
    almost_viable_model_name = singularize(snake_to_camel(table_name))
    return capitalize(almost_viable_model_name)


@caster(unicode)
def remove_table_prefix(table_name, table_prefix):
    return table_name.replace(table_prefix + '_',
                              '') if table_prefix else table_name


def file_writer(file_path, content):
    file_ = safe_open(file_path)
    file_.write(content)
    file_.flush()
    file_.close()
    print '%s generated' % file_path


def parse_columns(column_info):
    columns_iter = re.finditer(
        r"\$table->(?P<type>\w+)\(['\"](?P<name>\w*?)['\"][^>]*\)",
        column_info)
    column_dicts = map(funccaller('groupdict'), columns_iter)
    #return (dict _ for dict_ in column_dicts if not(dict_['name'] == 'id' or dict_['name'].endswith('id')))
    for dict_ in column_dicts:
        if dict_['name'] == 'id' or dict_['name'].endswith('id'):
            pass
        else:
            yield dict_


def parse_foreign_key_info(migration_file_content, table_name=r'.*?'):
    mo_iter = re.finditer(r"foreign\(['\"](?P<foreign_key>.*?)['\"]\)->"
                          r"references\(['\"](?P<references>.*?)['\"]\)->"
                          r"on\(['\"](?P<foreign_table>%s)['\"]\)" %
                          table_name, migration_file_content)
    return map(funccaller('groupdict'), mo_iter)


def parse_migration_file(migration_file_content, table_name=r'.*?'):
    """Takes migration file content, returns columns..."""
    info_mo = re.search(r'Schema::create\([\'"]'
                        r'(?P<table_name>\w+)[\'"].*?\).*?\{'
                        r'(?P<column_info>[\s\S]+?)\}\);',
                        migration_file_content)
    info = info_mo.groupdict()
    column_dicts = list(parse_columns(info['column_info']))
    slugless_column_dicts = list(ifilterfalse(
        lambda d_: d_['name'] in ['slug', 'identifier'], column_dicts))

    return {
        'table_name': info['table_name'],
        'columns': column_dicts,
        'slugless_columns': slugless_column_dicts,
        'foreign_key_info':
        parse_foreign_key_info(info['column_info'], table_name)
    }


def extract_info(migration_file_content, table_name=r'.*?', table_prefix=''):
    info = parse_migration_file(migration_file_content, table_name)
    info['table_name_stripped'] = remove_table_prefix(info['table_name'],
                                                      table_prefix)
    info['model_name'] = table_name_to_model_name(info['table_name'])
    info['singular'] = singularize(info['table_name_stripped'])
    info['singular_slugged'] = slugify(info['singular'])
    info['plural'] = pluralize(info['singular'])
    info['plural_slugged'] = slugify(info['plural'])
    #I think there could me multiple foreign keys to one table. If I use the table names,
    #there might be erronous repetition or over writing, better to use the foreign key instead of table name
    #for many to many relationships
    info['relationship'] = snake_to_camel(info['singular'])
    info['relationship_cap'] = capitalize(info['relationship'])
    info['relationship_plural'] = snake_to_camel(info['table_name_stripped'])
    info['relationship_cap_plural'] = pluralize(info['relationship_cap'])
    info['relationship_spaced'] = snake_to_spaced(info['singular'])
    info['relationship_spaced_plural'] = snake_to_spaced(info['plural'])

    foreign_key_info_list = info['foreign_key_info']
    for index, foreign_key_info in enumerate(foreign_key_info_list[:]):
        foreign_key_info_list[index].update({
            'relationship': snake_to_camel(foreign_key_info[
                'foreign_key'].replace('_id', '')),
            'relationship_spaced': snake_to_spaced(foreign_key_info[
                'foreign_key'].replace('_id', '')),
            'relationship_spaced_plural': pluralize(snake_to_spaced(
                foreign_key_info['foreign_key'].replace('_id', ''))),
            'relationship_snake': foreign_key_info['foreign_key'].replace(
                '_id', ''),
            'relationship_snake_plural': pluralize(foreign_key_info[
                'foreign_key'].replace('_id', '')),
            'model_name': table_name_to_model_name(foreign_key_info[
                'foreign_table']),
            'relationship_cap': capitalize(snake_to_camel(foreign_key_info[
                'foreign_key'].replace('_id', ''))),
        })
    return info


def big(migration_file_path, table_prefix=''):
    migrations_path = migration_file_path.rpartition('/')[
        0
    ]  # better if there was a default to fall back on?
    file_content = file(migration_file_path).read()
    current_file_info = extract_info(file_content, table_prefix=table_prefix)

    grep_line = "grep -R '\$table.*%s' %s" % (current_file_info['table_name'],
                                              migrations_path)
    grep_results = os.popen(grep_line).read().strip()

    try:
        external_file_contents = map(
            compose(file.read, file, itemgetter(0),
                    funccaller('split', ':')), grep_results.split('\n'))
        other_files_info = map(
            partial(extract_info,
                    table_name=current_file_info['table_name'],
                    table_prefix=table_prefix),
            external_file_contents)
    except IOError, e:
        other_files_info = []

    info = {}
    info['internal_info'] = current_file_info
    info['external_info'] = other_files_info
    info['internal_info']['relationships'] = map(itemgetter('relationship_plural'), other_files_info) +\
                                             map(itemgetter('relationship'), current_file_info['foreign_key_info'])
    return info


def add_router_model(route_type, info):
    route_service_provider = safe_open(route_type['list_path'], 'r+').read()
    binding = route_type['template'].render(info)
    pattern = re.compile(
        r'(^\s+\$router->model\(.*?, .*?\);\n)(\n^\s+\$router->bind\()',
        re.MULTILINE)
    if re.search(r'[\s\S]+%s[\s\S]+' % binding.strip(), route_service_provider,
                 re.DOTALL):
        print 'Binding already exists'
    else:
        file_writer(route_type['list_path'],
                    pattern.sub(r'\1%s\2' % binding, route_service_provider))


def add_router_binding(route_type, info):
    route_service_provider = safe_open(route_type['list_path'], 'r+').read()
    binding = route_type['template'].render(info)
    if route_service_provider.find('\n'.join(binding.split('\n')[:4])) == -1:
        route_service_provider = re.sub(r'(\s+parent::boot\(\$router\);)',
                                        r'%s\1' % binding,
                                        route_service_provider, re.M)
        file_writer(route_type['list_path'], route_service_provider)
    else:
        print 'Binding already exists'


def add_routes(route_type, info):
    # balancing braces and all that
    pass


def add_api_routes(route_type, info):
    # balancing braces and all that
    pass


def add_factory(info):
    template = env.get_template('factory.txt')
    rendered_factory = template.render(info)
    model_factory = file('database/factories/ModelFactory.php', 'a')
    model_factory.write(rendered_factory)
    model_factory.flush()
    model_factory.close()


def real_main(migration_file_path, args):
    try:
        print '\nMigration file: ', migration_file_path.rpartition('/')[-1]
        info = big(migration_file_path, table_prefix=args.prefix)
        info['folder'] = args.folder
        info['namespace_suffix'] = info['folder'].replace('/', '\\')
        route_type, info['identifier'] = (
            route_types['model'], 'id') if args.id else choose_identifier(info[
                'internal_info']['columns'])
        info['views_dotpath'] = re.sub(
            r'[/\\]+', '.',
            "{folder}.{internal_info[singular_slugged]}".format(
                **info)).lower()
        info['views_path'] = info['views_dotpath'].replace('.', '/')
        info['route_prefix'] = re.sub(
            r'[/\\]+', '.',
            "cms.{folder}.{internal_info[plural_slugged]}".format(
                **info)).lower()
        info['faker_types'] = faker_types
        all_views = partial(map, finisher(info), view_types.values())

        current_finisher = finisher(info)
        cms_acceptance = lambda : current_finisher(test_types['cms_acceptance'])
        api_acceptance = lambda : current_finisher(test_types['api_acceptance'])
        cms_acceptance()
        #import pdb;pdb.set_trace()
        if hasattr(args, 'all'):
            map(current_finisher, file_types.values())
        else:
            for key, truth_value in args._get_kwargs():
                if truth_value and key in file_types:
                    current_finisher(file_types[key])
                if truth_value and key == 'seeder':
                    map(current_finisher, seeder_types.values())
                if truth_value and key == 'all_views':
                    all_views()

        return info
    except AttributeError, e:
        print 'Error: ', e, 'File: ', migration_file_path


env = Environment(loader=FileSystemLoader(os.path.dirname(os.path.realpath(
    __file__)) + '/templates'))

file_types = {
    'model': {
        'template': env.get_template('model.txt'),
        'path_template': 'app/Models/{internal_info[model_name]}.php'
    },
    'transformer': {
        'template': env.get_template('transformer.txt'),
        'path_template':
        'app/Transformer/V1/{internal_info[model_name]}Transformer.php'
    },
    'api_controller': {
        'template': env.get_template('api_controller.txt'),
        'path_template':
        'app/Api/V1/Controllers/{folder}/{internal_info[model_name]}Controller.php'
    },
    'controller': {
        'template': env.get_template('controller.txt'),
        'path_template':
        'app/Http/Controllers/{folder}/{internal_info[model_name]}Controller.php'
    },
    'request': {
        'template': env.get_template('request.txt'),
        'path_template':
        'app/Http/Requests/{folder}/{internal_info[model_name]}Request.php'
    },
}

view_types = {
    'index': {
        'template': env.get_template('blade/index.blade.txt'),
        'path_template': 'resources/views/{views_path}/index.blade.php'
    },
    'create_or_edit': {
        'template': env.get_template('blade/create_or_edit.blade.txt'),
        'path_template':
        'resources/views/{views_path}/create_or_edit.blade.php'
    },
    'view': {
        'template': env.get_template('blade/view.blade.txt'),
        'path_template': 'resources/views/{views_path}/view.blade.php'
    },
}
"""
'create': {
    'template': env.get_template('blade/create.blade.txt'),
    'path_template': 'resources/views/{views_path}/create.blade.php'
},
'edit': {
    'template': env.get_template('blade/edit.blade.txt'),
    'path_template': 'resources/views/{views_path}/edit.blade.php'
},
"""

route_types = {
    'binding': {
        'template': env.get_template('routes/binding.txt'),
        'list_path': 'app/Providers/RouteServiceProvider.php',
        'updater': add_router_binding,
    },
    'model': {
        'template': env.get_template('routes/model.txt'),
        'list_path': 'app/Providers/RouteServiceProvider.php',
        'updater': add_router_model,
    },
    'api': {
        'template': env.get_template('routes/api.txt'),
        'list_path': 'app/Api/routes.php',
        'updater': add_api_routes,
    },
    'route': {
        'template': env.get_template('routes/vanilla.txt'),
        'list_path': 'app/Http/routes.php',
        'updater': add_routes,
    },
}

seeder_types = {
    'test': {
        'template': env.get_template('seeders/test.txt'),
        'path_template':
        'database/seeds/test/{internal_info[model_name]}TableSeeder.php'
    },
    'local': {
        'template': env.get_template('seeders/local.txt'),
        'path_template':
        'database/seeds/local/{internal_info[model_name]}TableSeeder.php'
    },
    'staging': {
        'template': env.get_template('seeders/staging.txt'),
        'path_template':
        'database/seeds/staging/{internal_info[model_name]}TableSeeder.php'
    },
}

test_types = {
    'api_acceptance': {
        'template': env.get_template('features/api.feature.txt'),
        'path_template':
        'tests/acceptance/api/{internal_info[model_name]}.feature'
    },
    'cms_acceptance': {
        'template': env.get_template('features/cms.feature.txt'),
        'path_template':
        'tests/acceptance/cms/{internal_info[model_name]}.feature'
    },
}

faker_types = {
    'text': '$faker->word(2)',
    'boolean': '$faker->randomElement([0, 1])',
    'date': '$faker->dateTimeThisYear',
    'enum': 0,
    'string': '$faker->word',
}
"""
input_types = {
        'integer'
        template
"""


def choose_identifier(columns):
    columns = ['id'] + map(itemgetter('name'), columns)
    for index, column in enumerate(columns):
        print "%d - %s" % (index, column)
    input_ = raw_input('Choose one: ')
    try:
        identifier_column = int(input_)
    except Exception:
        identifier_column = 0
    return route_types['binding' if identifier_column else 'model'], columns[
        identifier_column]


def finisher(information_dict):
    def inner(file_type):
        file_type['template'].globals.update(**globals())
        file_type['template'].globals.update(**locals())
        file_type['template'].globals['len'] = len
        content = file_type['template'].render(information_dict)
        path = file_type['path_template'].format(**information_dict)
        file_writer(path, content)

    return inner


def main():
    if 'artisan' not in listdir(os.getcwd()):
        print 'Please be in the project\'s base directory'
        exit()

    parser = argparse.ArgumentParser(
        prog='PyRavel',
        description="Generate stupid-ass laravel stuff")

    parser.add_argument("folder",
                        help="subdirectory where to put the generated stuff")
    parser.add_argument("prefix", help="table prefix to remove")
    parser.add_argument("--id",
                        help="assume identifier to be id",
                        action="store_true")

    parser.add_argument("-m",
                        "--model",
                        help="generate eloquent model",
                        action="store_true")
    parser.add_argument("-t",
                        "--transformer",
                        help="generate fractal transformer",
                        action="store_true")
    parser.add_argument("-C",
                        "--api_controller",
                        help="generate dingo api controller",
                        action="store_true")
    parser.add_argument("-c",
                        "--controller",
                        help="generate laravel controller",
                        action="store_true")
    parser.add_argument("-r",
                        "--request",
                        help="generate laravel request",
                        action="store_true")
    parser.add_argument("-s",
                        "--seeder",
                        help="generate seeders",
                        action="store_true")
    parser.add_argument("-V",
                        "--all-views",
                        help="generate all views",
                        action="store_true")

    # parser.add_argument("-A", "--all", help="generate laravel everything", action="store_false")
    parser.add_argument("migrations", help="migration files[s]", nargs='+')
    args = parser.parse_args()

    #passing table name instead of migrations?
    #raw_input('\n'.join(args.migrations))
    #migrations = args.migrations[0].replace("'", '').split(' ')
    info_list = map(partial(real_main, args=args), args.migrations)
    for type_, content in route_types.items():
        for info in info_list:
            print content['template'].render(info)


if __name__ == '__main__':
    main()
