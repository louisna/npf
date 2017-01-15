#!/usr/bin/python3
import argparse

from src import npf
from src.regression import *


class Comparator():
    def __init__(self, repo_list: List[Repository], quiet: bool, force_test:bool, overriden_variables:Dict = {}):
        self.repo_list = repo_list
        self.quiet = quiet
        self.force_test = force_test
        self.overriden_variables = overriden_variables

    def run(self, testie_name, tags):
        graphs_series = []
        for repo in self.repo_list:
            regressor = Regression(repo)
            testies = Testie.expand_folder(testie_name, tags=repo.tags + tags)
            for testie in testies:
                testie.variables.override_all(self.overriden_variables)
                build, datasets = regressor.regress_all_testies(testies=[testie], quiet=self.quiet, force_test = self.force_test)
                build._pretty_name = repo.reponame
                graphs_series.append((testie, build, datasets[0]))

        if len(graphs_series) == 0:
            print("No valid tags/testie/repo combination.")
            return

        return graphs_series


def main():
    parser = argparse.ArgumentParser(description='NPF cross-repository comparator')
    parser.add_argument('repos', metavar='repo', type=str, nargs='+', help='names of the repositories to watch');
    parser.add_argument('--quiet', help='Quiet mode', dest='quiet', action='store_true', default=False)
    parser.add_argument('--output', metavar='filename', type=str, nargs=1, default=None,
                        help='path to the file to output the graph');

    t = npf.add_testing_options(parser)

    args = parser.parse_args();

    # Parsing repo list and getting last_build
    repo_list = []
    for repo_name in args.repos:
        repo = Repository(repo_name)
        repo.last_build = None
        repo_list.append(repo)

    comparator = Comparator(repo_list,
                            quiet=args.quiet,
                            force_test=args.force_test,
                            overriden_variables = npf.parse_variables(args.variables))

    series = comparator.run(testie_name=args.testie, tags=args.tags)

    if series is None:
        return

    if args.output is None:
        filename = 'compare/' + os.path.splitext(os.path.basename(args.testie))[0] + '_' +  '_'.join(["%s" % repo.reponame for repo in repo_list]) + '.pdf';
    else:
        filename = args.output[0]

    dir = Path(os.path.dirname(filename))
    if not dir.exists():
        os.makedirs(dir.as_posix())

    grapher = Grapher()
    g = grapher.graph(series=series,
                      filename=filename)


if __name__ == "__main__":
    main()