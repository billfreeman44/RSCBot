import traceback
import ast
import random
from datetime import datetime
import json
import discord
from .config import config

from redbot.core import Config
from redbot.core import commands
from redbot.core import checks

defaults = {"MatchDay": 0, "Schedule": {}, "Game": "Rocket League"}

class Match(commands.Cog):
    """Used to get the match information"""

    MATCHES_KEY = "Matches"
    TEAM_DAY_INDEX_KEY = "TeamDays"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567893, force_registration=True)
        self.config.register_guild(**defaults)
        self.team_manager = bot.get_cog("TeamManager")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def setMatchDay(self, ctx, day: str):
        """Sets the active match day to the specified day.

        This match day is used when accessing the info in the !match command.
        """
        await self._save_match_day(ctx, str(day))
        await ctx.send("Done")

    @commands.command()
    @commands.guild_only()
    async def getMatchDay(self, ctx):
        """Gets the currently active match day."""
        match_day = await self._match_day(ctx)
        if match_day:
            await ctx.send(
                "Current match day is: {0}".format(match_day))
        else:
            await ctx.send(":x: Match day not set. Set with setMatchDay "
                               "command.")

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def printScheduleData(self, ctx):
        """Print all raw schedule data.

        Note: In the real server, this will likely fail just due to the amount
        of data. Intended for use in debugging on test servers. Basically,
        when there are only a handful of matches total.

        TODO: Might even comment this out in prod.
        """
        schedule = await self._schedule(ctx)
        dump = json.dumps(schedule, indent=4, sort_keys=True)
        await ctx.send("Here is all of the schedule data in "
                           "JSON format.\n```json\n{0}\n```".format(dump))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clearSchedule(self, ctx):
        """Clear all scheduled matches."""
        await self._save_schedule(ctx, {})
        await ctx.send("Done.")

    @commands.command()
    @commands.guild_only()
    async def match(self, ctx, *args):
        """Get match info.

        If no arguments are provided, retrieve the match info for the
        server's currently active match day for the requesting user's
        team or teams. This will fail if the user has no team role or if
        the match day is not set.

        If one argument is provided, it must be the match day to retrieve. If
        more than one argument is provided, the first must be the match day
        followed by a list of teams for which the match info should be
        retrieved.

        Example: `[p]match 1 derechos "killer bees"`

        Note: If no team names are sent, GMs (or anyone with multiple team
        roles) will get matchups for all their teams. User's without a team
        role will get nothing.
        """
        match_day = args[0] if args else await self._match_day(ctx)
        if not match_day:
            await ctx.send("Match day not provided and not set for "
                               "the server.")
            return
        team_names = []
        user_team_names = await self.team_manager.teams_for_user(
            ctx, ctx.message.author)

        team_names_provided = len(args) > 1
        if team_names_provided:
            team_names = args[1:]
        else:
            team_names = user_team_names

        if not team_names:
            await ctx.send("No teams found. If you provided teams, "
                               "check the spelling. If not, you do not have "
                               "roles corresponding to a team.")
            return

        for team_name in team_names:
            match_index = await self._team_day_match_index(ctx, team_name,
                                                     match_day)
            if match_index is not None:
                if ctx.message.author.is_on_mobile():
                    message = await self._format_match_message(ctx, match_index, team_name)
                    await ctx.message.author.send(message)
                else:
                    embed = await self._format_match_embed(ctx, match_index, team_name)
                    await ctx.message.author.send(embed=embed)
            else:
                await ctx.message.author.send(
                    "No match on day {0} for {1}".format(match_day,
                                                         team_name)
                )
        await ctx.message.delete()

    @commands.command(aliases=['lobbyup', 'up'])
    @commands.guild_only()
    async def lobbyready(self, ctx):
        """Informs players of the opposing team that the private match lobby is ready and joinable."""
        match_day = await self._match_day(ctx)
        teams = await self.team_manager.teams_for_user(ctx, user)
        
        if not (match_day and teams):
            return

        team_name = teams[0]
        match_data = await self.get_match_from_day_team(ctx, match_day, team_name)

        if not match_data:
            return await ctx.send(":x: Match could not be found")

        opposing_team = match_data['home'] if team_name == match_data['away'] else match_data['away']
        
        opp_franchise_role, tier_role = await self._roles_for_team(ctx, opposing_team)
        opp_captain = await self.team_manager(ctx, opp_franchise_role, tier_role)
        opposing_roster = self.team_manager.members_from_team(ctx, opp_franchise_role, tier_role)
        opposing_roster.remove(opp_captain)
        
        message = "Please join your match against the **{}** with the following lobby information:".format(opposing_team)
        message += "\n\n**Name:** {}".format(match_data['roomName'])
        message += "\n**Password:** {}".format(match_data['roomPass'])
        
        embed = discord.Embed(title="Your Opponents are ready!", color=tier_role.color, description=message)

        # TODO: cover scenario where captain has promoted
        # only send to captain if in-game
        if await self._is_in_game(opp_captain):
            return await opp_captain.send(embed)
        
        # send to captain if status is online
        if opp_captain.status == "online":
            await opp_captain.send(embed)

        # send to all rostered players in-game if captain isn't in-game
        actively_playing = []
        for player in opposing_roster:
            if await self._is_in_game(player):
                actively_playing.append(player)
        
        if actively_playing:
            for player in actively_playing:
                await player.send(embed)
            return
        
        # send to all online players if no players are in-game
        online = []
        for player in opposing_roster:
            if player.status == "online":
                online.append(player)
        
        if online:
            for player in online:
                await player.send(embed)
            return

        # send to everyone if nobody is online, including opposing team's GM
        opposing_roster.append(opp_captain)
        for player in opposing_roster:
            await player.send(embed)
        
        # Don't double send to GM
        opposing_gm = self.team_manager._get_gm(ctx, opp_franchise_role)
        if opposing_gm in opposing_roster:
            return

        embed.description += "\n_This message has been sent to you because none of the players on your "
        embed.description += "{} team, the {} appear to be in-game or online._".format(tier_role.name, opposing_team)

        await opposing_gm.send(embed)
        await ctx.message.add_reaction("\U00002705") # white check mark
        # TODO: Maybe react with franchise emojis? could be fun :)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatches(self, ctx, *matches):
        """Add the matches provided to the schedule.

        Arguments:

        matches -- One or more matches in the following format:

        "['<matchDay>','<matchDate>','<home>','<away>','<roomName>','<roomPassword>']"

        Each match should be separated by a space. Also, matchDate should be
        formatted with the full month name, day of month and 4-digit year.
        The room name and password are optional. They will be generated if
        absent. Note that the placment of the double versus single quotes is
        important, as is the comma after the day of month.

        Examples:

        [p]addMatches "['1','September 10, 2020','Fire Ants','Leopards',
        'octane','worst car']"
        [p]addMatches "['1','September 10, 2018','Fire Ants','Leopards']" "[
        '2','September 13, 2018','Leopards','Fire Ants']"

        """
        addedCount = 0
        try:
            for matchStr in matches:
                match = ast.literal_eval(matchStr)
                resultMatch = await self._add_match(ctx, *match)
                if resultMatch:
                    addedCount += 1
        except Exception as e:
            await ctx.send(e)
        finally:
            await ctx.send("Added {0} match(es).".format(addedCount))

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def addMatch(self, ctx, match_day, match_date, home, away, *args):
        """Adds a single match to the schedule.

        Arguments:
            ctx -- the bot context
            match_day -- the match_day to add the match to
            match_date -- the date the match should be played
            home -- the home team (must match the role name)
            away -- the away team (must match the role name)
            roomName -- (optional) the name for the RL match lobby,
                        Autogenerated if not provided.
            roomPass -- (optional) the password for the match lobby.
                        Autogenerated if not provided.
        Note: Any "extra" arguments are ignored.
        """
        match = await self._add_match(ctx, match_day, match_date,
                                      home, away, *args)
        if match:
            await ctx.send("Done")


    async def _add_match(self, ctx, match_day, match_date, home, away, *args):
        """Does the actual work to save match data."""
        # Process inputs to normalize the data (e.g. convert team names to
        # roles)
        match_date_error = None
        try:
            datetime.strptime(match_date, '%B %d, %Y').date()
        except Exception as err:
            match_date_error = "Date not valid: {0}".format(err)
        homeRoles = await self.team_manager._roles_for_team(ctx, home)
        awayRoles = await self.team_manager._roles_for_team(ctx, away)
        roomName = args[0] if args else self._generate_name_pass()
        roomPass = args[1] if len(args) > 1 else self._generate_name_pass()

        # Validation of input
        # There are other validations we could do, but don't
        #     - that there aren't extra args
        errors = []
        if match_date_error:
            errors.append("Date provided is not valid. "
                          "(Make sure to use the right format.)")
        if not homeRoles:
            errors.append("Home team roles not found.")
        if not awayRoles:
            errors.append("Away team roles not found.")
        if errors:
            await ctx.send(":x: Errors with input:\n\n  "
                               "* {0}\n".format("\n  * ".join(errors)))
            return

        # Schedule "schema" in pseudo-JSON style:
        # "schedule": {
        #   "matches": [ <list of all matches> ],
        #   "teamDays": { <dict where keys are tuples of team role names and
        #                 match days with list of indexes of all matches> }
        # }

        # Load the data we will use. Race conditions are possible, but
        # our change will be consistent, it might just override what someone
        # else does if they do it at roughly the same time.
        schedule = await self._schedule(ctx)
        # Check for pre-existing matches
        home_match_index = await self._team_day_match_index(
            ctx, home, match_day)
        away_match_index = await self._team_day_match_index(
            ctx, away, match_day)
        errors = []
        if home_match_index is not None:
            errors.append("Home team already has a match for "
                          "match day {0}".format(match_day))
        if away_match_index is not None:
            errors.append("Away team already has a match for "
                          "match day {0}".format(match_day))
        if errors:
            await ctx.send(":x: Could not create match:\n"
                               "\n  * {0}\n".format("\n  * ".join(errors)))
            return

        match_data = {
            'matchDay': match_day,
            'matchDate': match_date,
            'home': home,
            'away': away,
            'roomName': roomName,
            'roomPass': roomPass,
            'streamDetails': None
        }

        # Append new match and create an index in "teamDays" for both teams.
        matches = schedule.setdefault(self.MATCHES_KEY, [])
        team_days = schedule.setdefault(self.TEAM_DAY_INDEX_KEY, {})

        home_key = self._team_day_key(home, match_day)
        team_days[home_key] = len(matches)

        away_key = self._team_day_key(away, match_day)
        team_days[away_key] = len(matches)

        matches.append(match_data)

        await self._save_schedule(ctx, schedule)

        result = match_data.copy()
        result['home'] = home
        result['away'] = away
        return result

    async def _set_match_on_stream(self, ctx, match_day, team, stream_details):
        matches = await self._matches(ctx)
        for match in matches:
            if match['matchDay'] == match_day and (one_team == match['home'] or one_team == match['away']):
                match['streamDetails'] = stream_details
                #match['time'] = time  # ((could add time param to match))
                await self._save_matches(ctx, matches)
                return True
        return False

    async def _schedule(self, ctx):
        return await self.config.guild(ctx.guild).Schedule()

    async def _save_schedule(self, ctx, schedule):
        await self.config.guild(ctx.guild).Schedule.set(schedule)

    async def _matches(self, ctx):
        schedule = await self._schedule(ctx)
        return schedule.setdefault(self.MATCHES_KEY, {})

    async def _save_matches(self, ctx, matches):
        schedule = await self._schedule(ctx)
        schedule[self.MATCHES_KEY] = matches
        await self._save_schedule(ctx, schedule)

    async def _team_days_index(self, ctx):
        schedule = await self._schedule(ctx)
        return schedule.setdefault(self.TEAM_DAY_INDEX_KEY, {})

    async def _save_team_days_index(self, ctx, team_days_index):
        schedule = await self._schedule(ctx)
        schedule[self.TEAM_DAY_INDEX_KEY] = team_days_index
        await self._save_schedule(ctx, schedule)

    async def _match_day(self, ctx):
        return await self.config.guild(ctx.guild).MatchDay()

    async def _save_match_day(self, ctx, match_day):
        await self.config.guild(ctx.guild).MatchDay.set(match_day)

    async def _team_day_match_index(self, ctx, team, match_day):
        team_days_index = await self._team_days_index(ctx)
        team_days_index =  {k.lower(): (v.lower() if isinstance(v, str) else v) for k, v in team_days_index.items()}
        if isinstance(match_day, str):
            match_day = match_day.lower()
        return team_days_index.get(
            self._team_day_key(team.lower(), match_day))

    def _team_day_key(self, team, match_day):
        return "{0}|{1}".format(team, match_day)

    async def _format_match_embed(self, ctx, match_index, user_team_name):
        matches = await self._matches(ctx)
        match = matches[match_index]
        # Match format:
        # match_data = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass,
        #     'stream_details' : <stream details/None>
        # }
        home = match['home']
        away = match['away']

        tier_role = (await self.team_manager._roles_for_team(ctx, home))[1]

        title = "__Match Day {0}: {1}__\n".format(match['matchDay'], match['matchDate'])
        description = "**{0}**\n    versus\n**{1}**\n\n".format(home, away)

        embed = discord.Embed(title=title, description=description, color=tier_role.color)

        player_ratings = self.bot.get_cog("PlayerRatings")
        if player_ratings and await player_ratings.guild_has_players(ctx):
            return await self._create_solo_match_embed(ctx, embed, match, player_ratings, user_team_name, home, away)
            
        return await self._create_normal_match_embed(ctx, embed, match, user_team_name, home, away)

    async def _format_match_message(self, ctx, match_index, user_team_name):
        matches = await self._matches(ctx)
        match = matches[match_index]
        # Match format:
        # match_data = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass
        #     'stream_details`: {
        #         'live_stream': live_stream,
        #         'slot': slot,
        #         'time': time
        #      }
        # }
        home = match['home']
        away = match['away']

        message = "__Match Day {0}: {1}__\n".format(match['matchDay'], match['matchDate'])
        message += "**{0}**\n    versus\n**{1}**\n\n".format(home, away)


        player_ratings = self.bot.get_cog("PlayerRatings")
        if player_ratings and await player_ratings.guild_has_players(ctx):
            message += await self._create_solo_match_message(ctx, match, player_ratings, user_team_name, home, away)
            return message
            
        message += await self._create_normal_match_message(ctx, match, user_team_name, home, away)
        return message

    async def get_match_from_day_team(self, ctx, match_day, team_name):
        matches = await self._matches(ctx)
        # Match format:
        # match_data = {
        #     'matchDay': match_day,
        #     'matchDate': match_date,
        #     'home': home,
        #     'away': away,
        #     'roomName': roomName,
        #     'roomPass': roomPass
        # }
        for match in matches:
            if match['matchDay'] == match_day:
                if match['home'].casefold() == team_name.casefold() or match['away'].casefold() == team_name.casefold():
                    return match
        return None

    async def set_match_on_stream(self, ctx, match_day, team_name, stream_data):
        matches = await self._matches(ctx)
        for match in matches:
            if not match['matchDay'] == match_day:
                break 
            if match['home'] == team_name or match['away'] == team_name:
                match['streamDetails'] = stream_data
                await self._save_matches(ctx, matches)
                return True
        return False

    async def remove_match_from_stream(self, ctx, match_day, team_name):
        matches = await self._matches(ctx)
        for match in matches:
            if not match['matchDay'] == match_day:
                break 
            if match['home'] == team_name or match['away'] == team_name:
                match.pop('streamDetails', None)
                await self._save_matches(ctx, matches)
                return True
        return False

    def _create_additional_info(self, user_team_name, home, away, stream_details=None, is_playoffs=False):
        additional_info = ""
        if user_team_name:
            if stream_details:
                if user_team_name.casefold() == home.casefold():
                    additional_info += config.stream_info.format(
                        home_or_away='home', 
                        time_slot=stream_details['slot'],
                        time=stream_details['time'],
                        live_stream=stream_details['live_stream']
                    )
                elif user_team_name.casefold() == away.casefold():
                    additional_info += config.stream_info.format(
                        home_or_away='away', 
                        time_slot=stream_details['slot'],
                        time=stream_details['time'],
                        live_stream=stream_details['live_stream']
                    )
            else:
                if user_team_name == home:
                    additional_info += config.home_info
                elif user_team_name == away:
                    additional_info += config.away_info
                

        # TODO: Add other info (complaint form, disallowed maps,
        #       enable crossplay, etc.)
        # REGULAR SEASON INFO
        additional_info += config.regular_info
        # PLAYOFF INFO
        #additional_info += config.playoff_info
        return additional_info

    async def _create_normal_match_embed(self, ctx, embed, match, user_team_name, home, away):
        embed.add_field(name="Lobby Info", value="Name: **{0}**\nPassword: **{1}**"
                                        .format(match['roomName'], match['roomPass']), inline=False)
        embed.add_field(name="**Home Team:**",
                value=await self.team_manager.format_roster_info(ctx, home), inline=False)
        embed.add_field(name="**Away Team:**",
                value=await self.team_manager.format_roster_info(ctx, away), inline=False)

        try:
            additional_info = self._create_additional_info(user_team_name, home, away, stream_details=match['streamDetails'])
        except KeyError:
            additional_info = self._create_additional_info(user_team_name, home, away)

        embed.add_field(name="Additional Info:", value=additional_info)
        return embed

    async def _create_normal_match_message(self, ctx, match, user_team_name, home, away):
        message = "**Lobby Info:**\nName: **{0}**\nPassword: **{1}**\n\n".format(match['roomName'], match['roomPass'])
        message += "**Home Team:**\n{0}\n".format(await self.team_manager.format_roster_info(ctx, home))
        message += "**Away Team:**\n{0}\n".format(await self.team_manager.format_roster_info(ctx, away))

        try:
            message += self._create_additional_info(user_team_name, home, away, stream_details=match['streamDetails'])
        except KeyError:
            message += self._create_additional_info(user_team_name, home, away)

        return message

    async def _create_solo_match_embed(self, ctx, embed, match, player_ratings_cog, user_team_name, home, away):
        embed.add_field(name="**Home Team:**",
                value=await self.team_manager.format_roster_info(ctx, home), inline=False)
        embed.add_field(name="**Away Team:**",
                value=await self.team_manager.format_roster_info(ctx, away), inline=False)
        message = ""
        seed = await player_ratings_cog.get_player_seed(ctx, user_team_name)
        if seed:
            message += await self._create_solo_user_matchups_message(ctx, match, player_ratings_cog, user_team_name, home, away, seed)
        else:
            message += await self._create_generic_solo_matchups_message(ctx, player_ratings_cog, home, away)
        embed.add_field(name="Match Info:", value=message)
        return embed

    async def _create_solo_match_message(self, ctx, match, player_ratings_cog, user_team_name, home, away):
        message = "**Home Team:**\n{0}\n".format(await self.team_manager.format_roster_info(ctx, home))
        message += "**Away Team:**\n{0}\n".format(await self.team_manager.format_roster_info(ctx, away))
        seed = await player_ratings_cog.get_player_seed(ctx, user_team_name)
        if seed:
            message += await self._create_solo_user_matchups_message(ctx, match, player_ratings_cog, user_team_name, home, away, seed)
        else:
            message += await self._create_generic_solo_matchups_message(ctx, player_ratings_cog, home, away)
        return message

    async def _create_solo_user_matchups_message(self, ctx, match, player_ratings_cog, user_team_name, home, away, seed):
        message = ""
        if user_team_name.casefold() == home.casefold():
            ordered_opponent_names, ordered_opponent_seeds = await player_ratings_cog.get_ordered_opponent_names_and_seeds(ctx, seed, True, away)
            message += config.solo_home_info.format(seed)
            message += "\n\n**Lobby Info:**\nName: **{0}**\nPassword: **{1}**\n\n".format(match['roomName'] + str(seed), match['roomPass'] + str(seed))
            message += config.solo_home_match_info.format(config.first_match_descr, ordered_opponent_names[0], config.first_match_time)
            message += config.solo_home_match_info.format(config.second_match_descr, ordered_opponent_names[1], config.second_match_time)
            message += config.solo_home_match_info.format(config.third_match_descr, ordered_opponent_names[2], config.third_match_time)
        else:
            ordered_opponent_names, ordered_opponent_seeds = await player_ratings_cog.get_ordered_opponent_names_and_seeds(ctx, seed, False, home)
            message += config.solo_away_info.format(seed)
            message += "\n\n{0}".format(config.solo_away_match_info.format(config.first_match_descr, ordered_opponent_names[0], config.first_match_time, 
                match['roomName'] + str(ordered_opponent_seeds[0]), match['roomPass'] + str(ordered_opponent_seeds[0])))
            message += "\n\n{0}".format(config.solo_away_match_info.format(config.second_match_descr, ordered_opponent_names[1], config.second_match_time, 
                match['roomName'] + str(ordered_opponent_seeds[1]), match['roomPass'] + str(ordered_opponent_seeds[1])))
            message += "\n\n{0}".format(config.solo_away_match_info.format(config.third_match_descr, ordered_opponent_names[2], config.third_match_time, 
                match['roomName'] + str(ordered_opponent_seeds[2]), match['roomPass'] + str(ordered_opponent_seeds[2])))
        return message

    async def _create_generic_solo_matchups_message(self, ctx, player_ratings_cog, home, away):
        message = ""
        try:
            # First match
            message += "\n\nThe first **one game** series will begin at {0} and will include the following matchups: ".format(config.first_match_time)
            message += "```"
            message += await self._create_matchup_string(ctx, player_ratings_cog, home, away, 1, 3)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 2, 1)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 3, 2)
            message += "```"
            # Second match
            message += "\n\nThe second **one game** series will begin at {0} and will include the following matchups: ".format(config.second_match_time)
            message += "```"
            message += await self._create_matchup_string(ctx, player_ratings_cog, home, away, 1, 2)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 2, 3)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 3, 1)
            message += "```"
            # Third match
            message += "\n\nThe final **three game** series will begin at {0} and will include the following matchups: ".format(config.third_match_time)
            message += "```"
            message += await self._create_matchup_string(ctx, player_ratings_cog, home, away, 1, 1)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 2, 2)
            message += "\n" + await self._create_matchup_string(ctx, player_ratings_cog, home, away, 3, 3)
            message += "```"
        except:
            message = "There was an error getting the matchups for this match."
        return message

    async def _create_matchup_string(self, ctx, player_ratings_cog, home, away, home_seed, away_seed):
        away_player_nick = str((await player_ratings_cog.get_member_by_team_and_seed(ctx, away, away_seed)).nick) # We convert to string to handle None cases
        home_player_nick = str((await player_ratings_cog.get_member_by_team_and_seed(ctx, home, home_seed)).nick) # We convert to string to handle None cases
        return config.solo_matchup.format(away_player = away_player_nick, home_player = home_player_nick)

    def _generate_name_pass(self):
        return config.room_pass[random.randrange(len(room_pass))]

    async def _is_in_game(self, member):
        if not member.activities:
            return False 
        
        playing = False
        game = await self._get_guild_game(member.guild)

        for activity in member.activities:
            if type(activity) == discord.Game:
                if activity.name == game:
                    playing = True
                    try:
                        playing = not activity.end or activity.end > datetime.utcnow()
                    except:
                        playing = not activity.end
                    return playing

    async def _save_guild_game(self, guild, game):
        await self.config.guild(guild).Game.set(game)

    async def _get_guild_game(self, guild):
        return await self.config.guild(guild).Game()
    