# serverless-cron

Instead of having a DO droplet to manage the crontab on, why not have a Serverless service for anything I might need?

## Goal

Make it as simple as possible for me to go from having an idea of a job that should run regularly (web scraper, idk, etc.) and be able to write a simple function that will accomplish it without having to worry about infra or dependencies (too much).

[webtask.io](https://webtask.io) is a partial inspiration of what I want to achieve here.

The main service deploys to AWS Lambdas, though depending on the task it would make sense to also hook up Cloudflare Workers to be managed in this repo as well. Why split things across a million repos, it just makes it harder to organize.

## Dependencies

Keep life as simple as possible, I have a single dependencies file, no layers or junk, and just add to it when needed. Odds are this project will fall apart after 10 minutes of use, so no need to get fancy with the infra.

If I use this for many things, then it may be worth setting up to use Layers & split function dependencies. I can't currently deploy only a single function because it's all one package of dependency junk.

### Per Function Dependencies (Implement at a later date if it makes sense)

Search on [this page](https://www.serverless.com/plugins/serverless-python-requirements) for `Per-function requirements`.

Worst case scenario if something gets annoying, just create a new Serverless service in directory and don't connect it at all
to the main one in the repo.

It doesn't work with Pipfiles, so you have to generate with `pipenv lock -r > requirements.txt` if you want it to pick up the dependencies.

What's even simpler than this? Just have one overarching Pipfile rather than separating it out, does it really make a difference?
