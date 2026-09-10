import discord
from discord import app_commands
from discord.ext import commands
import io

TICKET_OPEN_CUSTOM_ID = "dbb_ticket_open"
TICKET_SELECT_CUSTOM_ID = "dbb_ticket_select"


class TicketConfigState:
    def __init__(self, guild_id: int, existing: dict | None):
        self.guild_id = guild_id
        self.category_id = existing.get("category_id") if existing else None
        self.panel_channel_id = existing.get("panel_channel_id") if existing else None
        self.panel_message = existing.get("panel_message", "Abre un ticket seleccionando una categoría abajo.") if existing else "Abre un ticket seleccionando una categoría abajo."
        self.categories = existing.get("categories", ["Soporte General"]) if existing else ["Soporte General"]
        self.open_type = existing.get("open_type", "select") if existing else "select"  # "select" o "buttons"


class TicketCategoryModal(discord.ui.Modal, title="Categorías de tickets"):
    def __init__(self, view: "TicketSetupView"):
        super().__init__()
        self.view_ref = view
        self.categories_input = discord.ui.TextInput(
            label="Categorías separadas por coma",
            style=discord.TextStyle.paragraph,
            default=", ".join(view.state.categories),
            max_length=300,
        )
        self.add_item(self.categories_input)

    async def on_submit(self, interaction: discord.Interaction):
        cats = [c.strip() for c in self.categories_input.value.split(",") if c.strip()]
        if cats:
            self.view_ref.state.categories = cats
        await self.view_ref.refresh(interaction)


class TicketPanelMessageModal(discord.ui.Modal, title="Mensaje del panel"):
    def __init__(self, view: "TicketSetupView"):
        super().__init__()
        self.view_ref = view
        self.message_input = discord.ui.TextInput(
            label="Mensaje del panel de tickets",
            style=discord.TextStyle.paragraph,
            default=view.state.panel_message,
            max_length=1000,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.state.panel_message = self.message_input.value
        await self.view_ref.refresh(interaction)


class TicketCategorySelectChannel(discord.ui.ChannelSelect):
    def __init__(self, view: "TicketSetupView"):
        super().__init__(
            placeholder="Categoría donde se crean los tickets",
            channel_types=[discord.ChannelType.category],
            min_values=1, max_values=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.category_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class TicketPanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "TicketSetupView"):
        super().__init__(
            placeholder="Canal donde se envía el panel",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.panel_channel_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class OpenTypeSelect(discord.ui.Select):
    def __init__(self, view: "TicketSetupView"):
        options = [
            discord.SelectOption(label="Select menu", value="select", description="Un menú desplegable"),
            discord.SelectOption(label="Botones", value="buttons", description="Un botón por categoría"),
        ]
        super().__init__(placeholder="Tipo de apertura", options=options, min_values=1, max_values=1)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.state.open_type = self.values[0]
        await self.view_ref.refresh(interaction)


class TicketSetupView(discord.ui.View):
    def __init__(self, bot, state: TicketConfigState):
        super().__init__(timeout=600)
        self.bot = bot
        self.state = state
        self.add_item(TicketCategorySelectChannel(self))
        self.add_item(TicketPanelChannelSelect(self))
        self.add_item(OpenTypeSelect(self))

    def build_preview(self) -> discord.Embed:
        embed = discord.Embed(
            title="Vista previa — Configuración de Tickets",
            description=self.state.panel_message,
            color=self.bot.embed_color,
        )
        embed.add_field(
            name="Categoría de canales",
            value=f"<#{self.state.category_id}>" if self.state.category_id else "No configurada",
        )
        embed.add_field(
            name="Canal del panel",
            value=f"<#{self.state.panel_channel_id}>" if self.state.panel_channel_id else "No configurado",
        )
        embed.add_field(name="Tipo de apertura", value=self.state.open_type, inline=False)
        embed.add_field(name="Categorías de tickets", value=", ".join(self.state.categories), inline=False)
        embed.set_footer(text=self.bot.footer_text)
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = self.build_preview()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Editar categorías", style=discord.ButtonStyle.secondary, row=3)
    async def edit_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketCategoryModal(self))

    @discord.ui.button(label="Editar mensaje del panel", style=discord.ButtonStyle.secondary, row=3)
    async def edit_panel_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketPanelMessageModal(self))

    @discord.ui.button(label="Guardar y enviar panel", style=discord.ButtonStyle.success, row=4)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.state.category_id or not self.state.panel_channel_id:
            await interaction.response.send_message(
                "Necesitás configurar la categoría y el canal del panel.", ephemeral=True
            )
            return
        data = {
            "category_id": self.state.category_id,
            "panel_channel_id": self.state.panel_channel_id,
            "panel_message": self.state.panel_message,
            "categories": self.state.categories,
            "open_type": self.state.open_type,
        }
        await self.bot.db.ticket_config.update_one(
            {"guild_id": self.state.guild_id}, {"$set": data}, upsert=True
        )
        channel = interaction.guild.get_channel(self.state.panel_channel_id)
        panel_embed = discord.Embed(
            title="🎫 Sistema de Tickets",
            description=self.state.panel_message,
            color=self.bot.embed_color,
        )
        panel_embed.set_footer(text=self.bot.footer_text)
        panel_view = build_open_view(self.state.categories, self.state.open_type)
        await channel.send(embed=panel_embed, view=panel_view)
        confirm_embed = discord.Embed(
            description=f"{self.bot.emojis['aceptar']} Configuración guardada y panel enviado en {channel.mention}.",
            color=self.bot.embed_color,
        )
        confirm_embed.set_footer(text=self.bot.footer_text)
        await interaction.response.edit_message(embed=confirm_embed, view=None)


def build_open_view(categories: list[str], open_type: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if open_type == "buttons":
        for cat in categories[:25]:
            view.add_item(TicketOpenButton(cat))
    else:
        view.add_item(TicketOpenSelect(categories))
    return view


class TicketOpenButton(discord.ui.Button):
    def __init__(self, category_name: str):
        super().__init__(
            label=category_name,
            style=discord.ButtonStyle.primary,
            custom_id=f"{TICKET_OPEN_CUSTOM_ID}:{category_name}",
        )

    async def callback(self, interaction: discord.Interaction):
        await create_ticket_channel(interaction, self.label)


class TicketOpenSelect(discord.ui.Select):
    def __init__(self, categories: list[str]):
        options = [discord.SelectOption(label=c, value=c) for c in categories[:25]]
        super().__init__(
            placeholder="Elegí una categoría para abrir un ticket",
            options=options,
            custom_id=TICKET_SELECT_CUSTOM_ID,
        )

    async def callback(self, interaction: discord.Interaction):
        await create_ticket_channel(interaction, self.values[0])


async def create_ticket_channel(interaction: discord.Interaction, category_name: str):
    bot = interaction.client
    config = await bot.db.ticket_config.find_one({"guild_id": interaction.guild_id})
    if not config:
        await interaction.response.send_message("El sistema de tickets no está configurado.", ephemeral=True)
        return

    existing = await bot.db.tickets.find_one(
        {"guild_id": interaction.guild_id, "user_id": interaction.user.id, "status": "open", "category_name": category_name}
    )
    if existing:
        await interaction.response.send_message("Ya tenés un ticket abierto en esta categoría.", ephemeral=True)
        return

    guild = interaction.guild
    category = guild.get_channel(config["category_id"])
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    guild_config = await bot.db.guild_config.find_one({"guild_id": guild.id})
    if guild_config:
        for role_id in guild_config.get("staff_roles", []):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    channel_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:90]
    channel = await guild.create_text_channel(
        name=channel_name, category=category, overwrites=overwrites,
        topic=f"Ticket de {interaction.user.id} | Categoría: {category_name}"
    )

    ticket_doc = {
        "guild_id": guild.id,
        "channel_id": channel.id,
        "user_id": interaction.user.id,
        "category_name": category_name,
        "status": "open",
        "claimed_by": None,
    }
    result = await bot.db.tickets.insert_one(ticket_doc)

    embed = discord.Embed(
        title=f"Ticket — {category_name}",
        description=f"Hola {interaction.user.mention}, en breve el staff te va a atender.\n\nUsá los botones para gestionar este ticket.",
        color=bot.embed_color,
    )
    embed.set_footer(text=bot.footer_text)
    view = TicketManageView(str(result.inserted_id))
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"Ticket creado: {channel.mention}", ephemeral=True)


class TicketManageView(discord.ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.claim.custom_id = f"dbb_ticket_claim:{ticket_id}"
        self.close.custom_id = f"dbb_ticket_close:{ticket_id}"
        self.delete.custom_id = f"dbb_ticket_delete:{ticket_id}"

    @discord.ui.button(label="Reclamar", style=discord.ButtonStyle.primary, emoji="🙋")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        from bson import ObjectId
        await bot.db.tickets.update_one(
            {"_id": ObjectId(self.ticket_id)}, {"$set": {"claimed_by": interaction.user.id}}
        )
        await interaction.response.send_message(f"Ticket reclamado por {interaction.user.mention}.")

    @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        from bson import ObjectId
        await bot.db.tickets.update_one({"_id": ObjectId(self.ticket_id)}, {"$set": {"status": "closed"}})
        overwrites = interaction.channel.overwrites
        for target, ow in list(overwrites.items()):
            if isinstance(target, discord.Member):
                ow.send_messages = False
                overwrites[target] = ow
        await interaction.channel.edit(overwrites=overwrites)
        await interaction.response.send_message("Ticket cerrado. Un staff puede eliminarlo cuando quiera.")

    @discord.ui.button(label="Eliminar Ticket", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Eliminando el ticket en 5 segundos...")
        bot = interaction.client
        from bson import ObjectId
        await bot.db.tickets.update_one({"_id": ObjectId(self.ticket_id)}, {"$set": {"status": "deleted"}})
        await discord.utils.sleep_until(discord.utils.utcnow() + __import__("datetime").timedelta(seconds=5))
        await interaction.channel.delete()


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Registrar vistas persistentes para paneles y tickets abiertos ya existentes
        self.bot.add_view(discord.ui.View(timeout=None))  # placeholder seguro
        configs = self.bot.db.ticket_config.find({})
        async for config in configs:
            view = build_open_view(config.get("categories", []), config.get("open_type", "select"))
            self.bot.add_view(view)
        open_tickets = self.bot.db.tickets.find({"status": {"$in": ["open", "closed"]}})
        async for t in open_tickets:
            self.bot.add_view(TicketManageView(str(t["_id"])))

    @app_commands.command(name="tickets-setup", description="Configura el sistema de tickets del servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tickets_setup(self, interaction: discord.Interaction):
        existing = await self.bot.db.ticket_config.find_one({"guild_id": interaction.guild_id})
        state = TicketConfigState(interaction.guild_id, existing)
        view = TicketSetupView(self.bot, state)
        embed = view.build_preview()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _get_ticket(self, channel_id: int):
        return await self.bot.db.tickets.find_one({"channel_id": channel_id, "status": {"$ne": "deleted"}})

    @commands.command(name="adduser")
    @commands.has_permissions(manage_channels=True)
    async def adduser(self, ctx, member: discord.Member):
        ticket = await self._get_ticket(ctx.channel.id)
        if not ticket:
            await ctx.send("Este comando solo puede usarse en un canal de ticket.")
            return
        await ctx.channel.set_permissions(member, view_channel=True, send_messages=True)
        await ctx.send(f"{member.mention} fue agregado al ticket.")

    @commands.command(name="removeuser")
    @commands.has_permissions(manage_channels=True)
    async def removeuser(self, ctx, member: discord.Member):
        ticket = await self._get_ticket(ctx.channel.id)
        if not ticket:
            await ctx.send("Este comando solo puede usarse en un canal de ticket.")
            return
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.send(f"{member.mention} fue removido del ticket.")

    @commands.command(name="close")
    @commands.has_permissions(manage_channels=True)
    async def close_cmd(self, ctx):
        ticket = await self._get_ticket(ctx.channel.id)
        if not ticket:
            await ctx.send("Este comando solo puede usarse en un canal de ticket.")
            return
        await self.bot.db.tickets.update_one({"_id": ticket["_id"]}, {"$set": {"status": "closed"}})
        await ctx.send("Ticket cerrado.")

    @commands.command(name="delete")
    @commands.has_permissions(manage_channels=True)
    async def delete_cmd(self, ctx):
        ticket = await self._get_ticket(ctx.channel.id)
        if not ticket:
            await ctx.send("Este comando solo puede usarse en un canal de ticket.")
            return
        await self.bot.db.tickets.update_one({"_id": ticket["_id"]}, {"$set": {"status": "deleted"}})
        await ctx.send("Eliminando el canal...")
        await ctx.channel.delete()

    @commands.command(name="rename")
    @commands.has_permissions(manage_channels=True)
    async def rename_cmd(self, ctx, *, new_name: str):
        ticket = await self._get_ticket(ctx.channel.id)
        if not ticket:
            await ctx.send("Este comando solo puede usarse en un canal de ticket.")
            return
        await ctx.channel.edit(name=new_name.lower().replace(" ", "-")[:90])
        await ctx.send("Canal renombrado.")


async def setup(bot):
    await bot.add_cog(Tickets(bot))
