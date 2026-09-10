import discord
from discord.ext import commands

# Sintaxis de uso por comando, para mostrar cuando el usuario lo usa mal
USAGE = {
    "lock": "?lock [#canal]",
    "unlock": "?unlock [#canal]",
    "ban": "?ban @usuario [razón]",
    "tempban": "?tempban @usuario <30s|5m|2h|1d|1w> [razón]",
    "unban": "?unban <ID_usuario> [razón]",
    "kick": "?kick @usuario [razón]",
    "mute": "?mute @usuario <30s|5m|2h|1d|1w> [razón]",
    "unmute": "?unmute @usuario",
    "timeout": "?timeout @usuario <30s|5m|2h|1d|1w> [razón]",
    "warn": "?warn @usuario [razón]",
    "warnings": "?warnings @usuario",
    "delwarn": "?delwarn @usuario <ID_warn>",
    "editreason": "?editreason @usuario <ID_warn> <nueva_razón>",
    "note": "?note @usuario <contenido>",
    "viewnotes": "?viewnotes @usuario",
    "delnote": "?delnote @usuario <ID_nota>",
    "slowmode": "?slowmode <segundos> [#canal]",
    "clear": "?clear <cantidad>",
    "dm": "?dm @usuario <mensaje>",
    "addrole": "?addrole @usuario @rol",
    "removerole": "?removerole @usuario @rol",
    "nick": "?nick @usuario [nuevo_apodo]",
    "userinfo": "?userinfo [@usuario]",
    "adduser": "?adduser @usuario",
    "removeuser": "?removeuser @usuario",
    "rename": "?rename <nuevo_nombre>",
}


def usage_embed(bot, ctx: commands.Context, detail: str) -> discord.Embed:
    syntax = USAGE.get(ctx.command.qualified_name, f"?{ctx.command.qualified_name}")
    embed = discord.Embed(
        title=f"{bot.custom_emojis['aviso']} Uso incorrecto del comando",
        description=detail,
        color=bot.embed_color,
    )
    embed.add_field(name="Sintaxis correcta", value=f"`{syntax}`", inline=False)
    embed.set_footer(text=bot.footer_text)
    return embed


class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # Ignorar comandos inexistentes para no spamear el canal
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=usage_embed(
                self.bot, ctx, f"Te falta el argumento **{error.param.name}**."
            ))
            return

        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=usage_embed(
                self.bot, ctx, "Uno de los argumentos que pusiste no es válido (¿mencionaste bien al usuario/canal/rol?)."
            ))
            return

        if isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=usage_embed(
                self.bot, ctx, f"No encontré a ningún usuario llamado **{error.argument}** en este servidor."
            ))
            return

        if isinstance(error, commands.RoleNotFound):
            await ctx.send(embed=usage_embed(
                self.bot, ctx, f"No encontré ningún rol llamado **{error.argument}**."
            ))
            return

        if isinstance(error, commands.ChannelNotFound):
            await ctx.send(embed=usage_embed(
                self.bot, ctx, f"No encontré ningún canal llamado **{error.argument}**."
            ))
            return

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{self.bot.custom_emojis['denegado']} Permisos insuficientes",
                description=f"Necesitás el permiso: **{perms}** para usar este comando.",
                color=self.bot.embed_color,
            )
            embed.set_footer(text=self.bot.footer_text)
            await ctx.send(embed=embed)
            return

        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{self.bot.custom_emojis['denegado']} Me faltan permisos",
                description=f"Necesito el permiso: **{perms}** para poder hacer esto.",
                color=self.bot.embed_color,
            )
            embed.set_footer(text=self.bot.footer_text)
            await ctx.send(embed=embed)
            return

        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Esperá {error.retry_after:.1f}s antes de volver a usar este comando.")
            return

        if isinstance(error, commands.CheckFailure):
            embed = discord.Embed(
                description=f"{self.bot.custom_emojis['denegado']} No tenés permiso para usar este comando.",
                color=self.bot.embed_color,
            )
            embed.set_footer(text=self.bot.footer_text)
            await ctx.send(embed=embed)
            return

        # Cualquier otro error no contemplado: lo mostramos en consola para debug
        print(f"Error no manejado en comando '{ctx.command}': {error}")
        embed = discord.Embed(
            description=f"{self.bot.custom_emojis['aviso']} Ocurrió un error inesperado al ejecutar este comando.",
            color=self.bot.embed_color,
        )
        embed.set_footer(text=self.bot.footer_text)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
