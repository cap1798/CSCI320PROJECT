import psycopg
from sshtunnel import SSHTunnelForwarder
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import hashlib
import os
import datetime
import random


# Hashes a password with a random salt.
def hash_password(password):
    salt = os.urandom(16)
    hashed_pass = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{hashed_pass.hex()}"


# Checks a provided password against a stored salt:hash string.
def check_password(stored_password, provided_password):
    try:
        salt_hex, hash_hex = stored_password.split(':')
        salt = bytes.fromhex(salt_hex)
        stored_hash = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    hashed_pass = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
    return hashed_pass == stored_hash


# Converts total minutes to 'HH:MM' format.
def format_duration(minutes):
    if minutes is None:
        return "00:00"
    try:
        total_minutes = int(minutes)
        hours = total_minutes // 60
        mins = total_minutes % 60
        return f"{hours:02}:{mins:02}"
    except (ValueError, TypeError):
        return "00:00"


# The main Tkinter application class that manages all frames and the DB connection.
class App(tk.Tk):
    # Initializes the main application window and database connection.
    def __init__(self, *args, **kwargs):
        tk.Tk.__init__(self, *args, **kwargs)
        self.title("Video Game Tracker")
        self.geometry("1024x700")

        try:
            with open('config.txt', 'r') as f:
                lines = f.readlines()
                self.username = lines[0].strip()
                self.password = lines[1].strip()
                self.dbName = lines[2].strip()
        except (IOError, IndexError):
            messagebox.showerror("Config Error",
                                 "Could not read config.txt.\n"
                                 "Make sure it exists and has 3 lines:\n"
                                 "username\npassword\ndbname")
            self.destroy()
            return

        self.conn = None
        self.curs = None
        self.server = None

        self.current_user_id = None

        if not self.connect_db():
            self.destroy()
            return

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (LoginFrame, RegisterFrame, MainAppFrame):
            page_name = F.__name__
            frame = F(parent=container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

    # Establishes the SSH tunnel and database connection.
    def connect_db(self):
        try:
            self.server = SSHTunnelForwarder(
                ('starbug.cs.rit.edu', 22),
                ssh_username=self.username,
                ssh_password=self.password,
                remote_bind_address=('127.0.0.1', 5432)
            )
            self.server.start()
            print("SSH tunnel established")

            params = {
                'dbname': self.dbName,
                'user': self.username,
                'password': self.password,
                'host': '127.0.0.1',
                'port': self.server.local_bind_port
            }
            self.conn = psycopg.connect(**params)
            self.curs = self.conn.cursor()
            print("Database connection established")
            return True
        except Exception as e:
            messagebox.showerror("Connection Failed", f"Could not connect to database:\n{e}")
            return False

    # Raises the specified frame to the top.
    def show_frame(self, page_name):
        frame = self.frames[page_name]
        if page_name == "MainAppFrame":
            frame.refresh_data()
        frame.tkraise()

    # Handles the window close event, closing the DB and SSH tunnel.
    def on_closing(self):
        if self.conn:
            self.conn.close()
            print("Database connection closed")
        if self.server:
            self.server.stop()
            print("SSH tunnel closed")
        self.destroy()


# The frame for the user login page.
class LoginFrame(tk.Frame):
    # Initializes the login UI components.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        frame = ttk.Frame(self, padding="30")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frame, text="Login", font=("Arial", 24)).pack(pady=20)

        ttk.Label(frame, text="Username").pack(pady=(0, 5))
        self.username_entry = ttk.Entry(frame, width=30)
        self.username_entry.pack()

        ttk.Label(frame, text="Password").pack(pady=(10, 5))
        self.password_entry = ttk.Entry(frame, show="*", width=30)
        self.password_entry.pack()

        ttk.Button(frame, text="Login", command=self.login).pack(pady=20, ipadx=10)
        ttk.Button(frame, text="Create Account", command=lambda: controller.show_frame("RegisterFrame")).pack()

    # Handles the login attempt.
    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password.")
            return

        try:
            # CORRECTED: "User", "UserID", "Password", "Username" -> users, userid, password, username
            self.controller.curs.execute(
                'SELECT userid, password FROM users WHERE username = %s',
                (username,)
            )
            user_data = self.controller.curs.fetchone()

            if user_data:
                user_id, stored_password = user_data

                if check_password(stored_password, password):
                    # CORRECTED: "User", "LastAccessDate", "UserID" -> users, lastaccessdate, userid
                    self.controller.curs.execute(
                        'UPDATE users SET lastaccessdate = %s WHERE userid = %s',
                        (datetime.datetime.now(), user_id)
                    )
                    self.controller.conn.commit()

                    self.controller.current_user_id = user_id
                    messagebox.showinfo("Success", f"Welcome, {username}!")
                    self.password_entry.delete(0, 'end')
                    self.controller.show_frame("MainAppFrame")
                else:
                    messagebox.showerror("Error", "Invalid username or password.")
            else:
                messagebox.showerror("Error", "Invalid username or password.")

        except Exception as e:
            messagebox.showerror("Database Error", f"An error occurred: {e}")
            self.controller.conn.rollback()


# The frame for the new user registration page.
class RegisterFrame(tk.Frame):
    # Initializes the registration UI components.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        frame = ttk.Frame(self, padding="30")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frame, text="Create Account", font=("Arial", 24)).grid(row=0, column=0, columnspan=2, pady=20)

        ttk.Label(frame, text="First Name:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.fname_entry = ttk.Entry(frame, width=30)
        self.fname_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Last Name:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.lname_entry = ttk.Entry(frame, width=30)
        self.lname_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Email:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        self.email_entry = ttk.Entry(frame, width=30)
        self.email_entry.grid(row=3, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        self.username_entry = ttk.Entry(frame, width=30)
        self.username_entry.grid(row=4, column=1, padx=5, pady=5)

        ttk.Label(frame, text="Password:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        self.password_entry = ttk.Entry(frame, show="*", width=30)
        self.password_entry.grid(row=5, column=1, padx=5, pady=5)

        ttk.Button(frame, text="Register", command=self.register).grid(row=6, column=0, columnspan=2, pady=20)
        ttk.Button(frame, text="Back to Login", command=lambda: controller.show_frame("LoginFrame")).grid(row=7,
                                                                                                          column=0,
                                                                                                          columnspan=2)

    # Handles the new user registration.
    def register(self):
        fname = self.fname_entry.get()
        lname = self.lname_entry.get()
        email = self.email_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not all([fname, lname, email, username, password]):
            messagebox.showerror("Error", "Please fill in all fields.")
            return

        hashed_password = hash_password(password)

        try:
            # CORRECTED: "User" and all columns to lowercase
            self.controller.curs.execute(
                """
                INSERT INTO users (firstname, lastname, email, username, password, creationdate)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (fname, lname, email, username, hashed_password, datetime.datetime.now())
            )
            self.controller.conn.commit()
            messagebox.showinfo("Success", "Account created successfully! Please log in.")
            for entry in [self.fname_entry, self.lname_entry, self.email_entry, self.username_entry,
                          self.password_entry]:
                entry.delete(0, 'end')
            self.controller.show_frame("LoginFrame")

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", "Username or email already exists.")
            else:
                messagebox.showerror("Database Error", f"An error occurred: {e}")


# The main application frame, containing the tabbed interface.
class MainAppFrame(tk.Frame):
    # Initializes the main app UI, including the notebook for tabs.
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent)
        self.controller = controller

        top_bar = ttk.Frame(self)
        top_bar.pack(side="top", fill="x", pady=5, padx=10)

        self.welcome_label = ttk.Label(top_bar, text="", font=("Arial", 14))
        self.welcome_label.pack(side="left")

        logout_button = ttk.Button(top_bar, text="Logout", command=self.logout)
        logout_button.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(side="top", fill="x", padx=10)

        self.notebook = ttk.Notebook(self)

        self.collections_frame = CollectionsFrame(self.notebook, self.controller)
        self.search_frame = SearchFrame(self.notebook, self.controller)
        self.social_frame = SocialFrame(self.notebook, self.controller)

        self.notebook.add(self.collections_frame, text="My Collections")
        self.notebook.add(self.search_frame, text="Search Games")
        self.notebook.add(self.social_frame, text="Social")

        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

    # Handles user logout.
    def logout(self):
        self.controller.current_user_id = None
        self.welcome_label.config(text="")
        self.controller.show_frame("LoginFrame")

    # Refreshes data in all tabs when the main frame is shown.
    def refresh_data(self):
        if self.controller.current_user_id:
            try:
                # CORRECTED: "FirstName", "User", "UserID" -> firstname, users, userid
                self.controller.curs.execute(
                    'SELECT firstname FROM users WHERE userid = %s',
                    (self.controller.current_user_id,)
                )
                user_name = self.controller.curs.fetchone()[0]
                self.welcome_label.config(text=f"Welcome, {user_name}!")
            except Exception as e:
                self.welcome_label.config(text="Welcome!")
                print(f"Error fetching user name: {e}")

            self.collections_frame.load_collections()
            self.social_frame.load_following()


# The frame for the "My Collections" tab.
class CollectionsFrame(ttk.Frame):
    # Initializes the collection management UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        list_frame = ttk.Frame(self)
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        cols = ("Name", "Game Count", "Total Playtime")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings")

        self.tree.heading("Name", text="Collection Name")
        self.tree.heading("Game Count", text="Games")
        self.tree.heading("Total Playtime", text="Playtime (HH:MM)")

        self.tree.column("Name", width=250)
        self.tree.column("Game Count", width=50, anchor="center")
        self.tree.column("Total Playtime", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        controls_frame = ttk.Frame(self, padding="10")
        controls_frame.pack(side="right", fill="y")

        ttk.Label(controls_frame, text="Manage Collections", font=("Arial", 16)).pack(pady=10)

        ttk.Label(controls_frame, text="New Collection Name:").pack(pady=(10, 5))
        self.new_collection_entry = ttk.Entry(controls_frame, width=30)
        self.new_collection_entry.pack()

        ttk.Button(controls_frame, text="Create Collection", command=self.create_collection).pack(pady=10)

        ttk.Separator(controls_frame, orient="horizontal").pack(fill="x", pady=10)

        ttk.Button(controls_frame, text="View/Manage Selected", command=self.view_collection_details).pack(pady=5,
                                                                                                           fill="x")
        ttk.Button(controls_frame, text="Play Random from Selected", command=self.play_random).pack(pady=5, fill="x")
        ttk.Button(controls_frame, text="Rename Selected", command=self.rename_collection).pack(pady=5, fill="x")
        ttk.Button(controls_frame, text="Delete Selected", command=self.delete_collection).pack(pady=5, fill="x")

        self.tree['displaycolumns'] = ("Name", "Game Count", "Total Playtime")
        self.tree["columns"] = ("CollectionID", "Name", "Game Count", "Total Playtime")
        self.tree.column("CollectionID", width=0, stretch=tk.NO)

    # Fetches and displays all collections for the current user.
    def load_collections(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            # CORRECTED: All tables and columns to lowercase
            sql = """
                SELECT 
                    c.collectionid,
                    c.name, 
                    COUNT(DISTINCT cg.gameid) AS gamecount,
                    COALESCE(SUM(p.duration), 0) AS totaldurationminutes
                FROM 
                    collection c
                LEFT JOIN 
                    collectiongame cg ON c.collectionid = cg.collectionid
                LEFT JOIN 
                    plays p ON cg.gameid = p.gameid AND c.userid = p.userid
                WHERE 
                    c.userid = %s
                GROUP BY 
                    c.collectionid, c.name
                ORDER BY 
                    c.name ASC;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id,))

            for row in self.controller.curs.fetchall():
                collection_id, name, game_count, total_minutes = row
                playtime_str = format_duration(total_minutes)
                self.tree.insert("", "end", values=(collection_id, name, game_count, playtime_str))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load collections: {e}")
            self.controller.conn.rollback()

    # Creates a new collection for the user.
    def create_collection(self):
        new_name = self.new_collection_entry.get()
        if not new_name:
            messagebox.showwarning("Warning", "Please enter a name for the new collection.")
            return

        try:
            # CORRECTED: "Collection", "UserID", "Name" -> collection, userid, name
            sql = 'INSERT INTO collection (userid, name) VALUES (%s, %s)'
            self.controller.curs.execute(sql, (self.controller.current_user_id, new_name))
            self.controller.conn.commit()

            self.new_collection_entry.delete(0, 'end')
            self.load_collections()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", "A collection with this name already exists.")
            else:
                messagebox.showerror("Database Error", f"Failed to create collection: {e}")

    # Helper to get the CollectionID and Name of the selected item.
    def get_selected_collection(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a collection from the list first.")
            return None, None

        item_data = self.tree.item(selected_item)
        collection_id = item_data['values'][0]
        collection_name = item_data['values'][1]
        return collection_id, collection_name

    # Renames the selected collection.
    def rename_collection(self):
        collection_id, current_name = self.get_selected_collection()
        if not collection_id:
            return

        new_name = simpledialog.askstring("Rename Collection",
                                          "Enter new name:",
                                          initialvalue=current_name)

        if not new_name:
            return

        try:
            # CORRECTED: "Collection", "Name", "CollectionID", "UserID" -> collection, name, collectionid, userid
            sql = 'UPDATE collection SET name = %s WHERE collectionid = %s AND userid = %s'
            self.controller.curs.execute(sql, (new_name, collection_id, self.controller.current_user_id))
            self.controller.conn.commit()
            self.load_collections()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", "A collection with this name already exists.")
            else:
                messagebox.showerror("Database Error", f"Failed to rename collection: {e}")

    # Deletes the selected collection after confirmation.
    def delete_collection(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        if not messagebox.askyesno("Confirm Delete",
                                   f"Are you sure you want to delete the collection '{collection_name}'?\n"
                                   "All games in this collection will be removed from it (but not deleted from the system)."):
            return

        try:
            # CORRECTED: "CollectionGame", "CollectionID" -> collectiongame, collectionid
            sql_games = 'DELETE FROM collectiongame WHERE collectionid = %s'
            self.controller.curs.execute(sql_games, (collection_id,))

            # CORRECTED: "Collection", "CollectionID", "UserID" -> collection, collectionid, userid
            sql_coll = 'DELETE FROM collection WHERE collectionid = %s AND userid = %s'
            self.controller.curs.execute(sql_coll, (collection_id, self.controller.current_user_id))

            self.controller.conn.commit()
            self.load_collections()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to delete collection: {e}")

    # Logs a play session for a random game from the selected collection.
    def play_random(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        try:
            # CORRECTED: "GameID", "CollectionGame", "CollectionID" -> gameid, collectiongame, collectionid
            sql = """
                SELECT gameid FROM collectiongame 
                WHERE collectionid = %s 
                ORDER BY random() LIMIT 1
            """
            self.controller.curs.execute(sql, (collection_id,))
            result = self.controller.curs.fetchone()

            if not result:
                messagebox.showinfo("Empty Collection", f"The collection '{collection_name}' has no games in it.")
                return

            game_id = result[0]

            duration = simpledialog.askinteger("Log Play Session", "How many minutes did you play?", minvalue=1)
            if not duration:
                return

            # CORRECTED: "Plays" and all columns to lowercase
            sql_play = """
                INSERT INTO plays (userid, gameid, playdatetime, duration)
                VALUES (%s, %s, %s, %s)
            """
            self.controller.curs.execute(sql_play,
                                         (self.controller.current_user_id, game_id, datetime.datetime.now(), duration))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"Logged {duration} minutes for a random game from '{collection_name}'.")
            self.load_collections()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to play random game: {e}")

    # Opens a new window to view/manage games within a collection.
    def view_collection_details(self):
        collection_id, collection_name = self.get_selected_collection()
        if not collection_id:
            return

        CollectionDetailWindow(self, collection_id, collection_name, self.controller)


# A new Toplevel window for managing games in a single collection.
class CollectionDetailWindow(tk.Toplevel):
    # Initializes the collection detail UI.
    def __init__(self, parent_frame, collection_id, collection_name, controller):
        tk.Toplevel.__init__(self, parent_frame)
        self.transient(parent_frame)
        self.grab_set()

        self.controller = controller
        self.collection_id = collection_id
        self.parent_frame = parent_frame

        self.title(f"Managing: {collection_name}")
        self.geometry("600x400")

        list_frame = ttk.Frame(self, padding="10")
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        cols = ("Title", "ESRB")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings")
        self.tree.heading("Title", text="Game Title")
        self.tree.heading("ESRB", text="Age Rating")
        self.tree.column("ESRB", width=80, anchor="center")

        self.tree['displaycolumns'] = ("Title", "ESRB")
        self.tree["columns"] = ("GameID", "Title", "ESRB")
        self.tree.column("GameID", width=0, stretch=tk.NO)

        self.tree.pack(fill="both", expand=True)

        controls_frame = ttk.Frame(self, padding="10")
        controls_frame.pack(side="right", fill="y")

        ttk.Button(controls_frame, text="Remove Selected Game", command=self.remove_game).pack(pady=10)
        ttk.Button(controls_frame, text="Close", command=self.close).pack(pady=5)

        self.load_games()

    # Loads games for the *specific* collection.
    def load_games(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            # CORRECTED: "GameID", "Title", "ESRB Rating", "VideoGame", "CollectionGame", "CollectionID"
            # -> gameid, title, esrb_rating, videogame, collectiongame, collectionid
            sql = """
                SELECT g.gameid, g.title, g.esrb_rating
                FROM videogame g
                JOIN collectiongame cg ON g.gameid = cg.gameid
                WHERE cg.collectionid = %s
                ORDER BY g.title ASC;
            """
            self.controller.curs.execute(sql, (self.collection_id,))

            for row in self.controller.curs.fetchall():
                self.tree.insert("", "end", values=row)

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load games in collection: {e}", parent=self)
            self.controller.conn.rollback()

    # Removes a selected game from this collection.
    def remove_game(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a game to remove.", parent=self)
            return

        game_id, game_title, _ = self.tree.item(selected_item)['values']

        if not messagebox.askyesno("Confirm", f"Remove '{game_title}' from this collection?", parent=self):
            return

        try:
            # CORRECTED: "CollectionGame", "CollectionID", "GameID" -> collectiongame, collectionid, gameid
            sql = 'DELETE FROM collectiongame WHERE collectionid = %s AND gameid = %s'
            self.controller.curs.execute(sql, (self.collection_id, game_id))
            self.controller.conn.commit()

            self.load_games()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to remove game: {e}", parent=self)

    # Closes the detail window and refreshes the main collections list.
    def close(self):
        self.parent_frame.load_collections()
        self.destroy()


# The frame for the "Search Games" tab.
class SearchFrame(ttk.Frame):
    # Initializes the game search UI.
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller
        self.search_results_data = []

        filter_frame = ttk.Frame(self)
        filter_frame.pack(side="top", fill="x", pady=(0, 10))

        ttk.Label(filter_frame, text="Game Title:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.title_entry = ttk.Entry(filter_frame, width=25)
        self.title_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="Developer:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.dev_entry = ttk.Entry(filter_frame, width=25)
        self.dev_entry.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="Platform:").grid(row=0, column=4, padx=5, pady=5, sticky="e")
        self.platform_entry = ttk.Entry(filter_frame, width=25)
        self.platform_entry.grid(row=0, column=5, padx=5, pady=5)

        ttk.Label(filter_frame, text="Genre:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.genre_entry = ttk.Entry(filter_frame, width=25)
        self.genre_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="Publisher:").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.pub_entry = ttk.Entry(filter_frame, width=25)
        self.pub_entry.grid(row=1, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="Release Year:").grid(row=1, column=4, padx=5, pady=5, sticky="e")
        self.year_entry = ttk.Entry(filter_frame, width=10)
        self.year_entry.grid(row=1, column=5, padx=5, pady=5, sticky="w")

        ttk.Label(filter_frame, text="Price (Max):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.price_entry = ttk.Entry(filter_frame, width=10)
        self.price_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        search_button = ttk.Button(filter_frame, text="Search", command=self.search_games)
        search_button.grid(row=0, column=6, rowspan=3, padx=20, ipady=10, sticky="ns")
        filter_frame.grid_columnconfigure(6, weight=1)

        results_frame = ttk.Frame(self)
        results_frame.pack(fill="both", expand=True, pady=(10, 0))

        cols = (
        "Title", "Year", "Price", "Platforms", "Developers", "Publisher", "My Playtime", "Age Rating", "My Rating")
        self.tree = ttk.Treeview(results_frame, columns=cols, show="headings")

        for col in cols:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_column(_col, False))

        self.tree.column("Title", width=200)
        self.tree.column("Year", width=50, anchor="center")
        self.tree.column("Price", width=50, anchor="center")
        self.tree.column("Platforms", width=110)
        self.tree.column("Developers", width=110)
        self.tree.column("Publisher", width=110)
        self.tree.column("My Playtime", width=80, anchor="center")
        self.tree.column("Age Rating", width=80, anchor="center")
        self.tree.column("My Rating", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree['displaycolumns'] = cols
        self.tree["columns"] = ("GameID", "Title", "Year", "Price", "Platforms", "Developers", "Publisher",
                                "My PlaytimeNum", "My Playtime", "Age Rating", "My RatingNum", "My Rating")

        self.tree.column("GameID", width=0, stretch=tk.NO)
        self.tree.column("My PlaytimeNum", width=0, stretch=tk.NO)
        self.tree.column("My RatingNum", width=0, stretch=tk.NO)

        action_frame = ttk.Frame(self)
        action_frame.pack(side="bottom", fill="x", pady=(10, 0))

        ttk.Button(action_frame, text="Add Selected to Collection...", command=self.add_to_collection).pack(side="left",
                                                                                                            padx=2)
        ttk.Button(action_frame, text="Rate Selected Game...", command=self.rate_game).pack(side="left", padx=2)
        ttk.Button(action_frame, text="Play Selected Game...", command=self.play_game).pack(side="left", padx=2)

    # Builds and executes a dynamic search query based on all filters.
    def search_games(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results_data = []

        try:
            # CORRECTED: All tables, columns, and aliases to lowercase
            base_sql = """
                SELECT 
                    g.gameid, 
                    g.title,
                    g.esrb_rating,
                    STRING_AGG(DISTINCT p.name, ', ') AS platforms,
                    STRING_AGG(DISTINCT dev.name, ', ') AS developers,
                    STRING_AGG(DISTINCT pub.name, ', ') AS publishers,
                    COALESCE(SUM(pl.duration), 0) AS totalplaytime,
                    pu.starrating,
                    MIN(EXTRACT(YEAR FROM gp.releasedate)) AS releaseyear,
                    MIN(gp.price) AS minprice,
                    MIN(gp.releasedate) AS minreleasedate
                FROM 
                    videogame g
                LEFT JOIN gameplatform gp ON g.gameid = gp.gameid
                LEFT JOIN platform p ON gp.platformid = p.platformid
                LEFT JOIN gamedeveloper gd ON g.gameid = gd.gameid
                LEFT JOIN company dev ON gd.companyid = dev.companyid
                LEFT JOIN gamepublisher gpub ON g.gameid = gpub.gameid
                LEFT JOIN company pub ON gpub.companyid = pub.companyid
                LEFT JOIN gamegenre gg ON g.gameid = gg.gameid
                LEFT JOIN genres gen ON gg.genreid = gen.genreid
                LEFT JOIN plays pl ON g.gameid = pl.gameid AND pl.userid = %s
                LEFT JOIN purchases pu ON g.gameid = pu.gameid AND pu.userid = %s
                WHERE 1=1
            """

            where_clauses = []
            params = [self.controller.current_user_id, self.controller.current_user_id]

            # CORRECTED: All query columns to lowercase
            if self.title_entry.get():
                where_clauses.append('g.title ILIKE %s')
                params.append(f"%{self.title_entry.get()}%")

            if self.dev_entry.get():
                where_clauses.append('dev.name ILIKE %s')
                params.append(f"%{self.dev_entry.get()}%")

            if self.pub_entry.get():
                where_clauses.append('pub.name ILIKE %s')
                params.append(f"%{self.pub_entry.get()}%")

            if self.genre_entry.get():
                where_clauses.append('gen.name ILIKE %s')
                params.append(f"%{self.genre_entry.get()}%")

            if self.platform_entry.get():
                where_clauses.append('p.name ILIKE %s')
                params.append(f"%{self.platform_entry.get()}%")

            if self.year_entry.get():
                try:
                    year = int(self.year_entry.get())
                    where_clauses.append('EXTRACT(YEAR FROM gp.releasedate) = %s')
                    params.append(year)
                except ValueError:
                    messagebox.showwarning("Warning", "Invalid Release Year. Must be a number. Year filter ignored.")

            if self.price_entry.get():
                try:
                    price = float(self.price_entry.get())
                    where_clauses.append('gp.price <= %s')
                    params.append(price)
                except ValueError:
                    messagebox.showwarning("Warning", "Invalid Price. Must be a number. Price filter ignored.")

            if where_clauses:
                base_sql += " AND " + " AND ".join(where_clauses)

            # CORRECTED: GROUP BY columns and ORDER BY alias
            base_sql += """
                GROUP BY g.gameid, g.title, g.esrb_rating, pu.starrating
                ORDER BY g.title ASC, minreleasedate ASC;
            """

            self.controller.curs.execute(base_sql, params)

            for row in self.controller.curs.fetchall():
                (game_id, title, esrb, platforms, devs, pubs,
                 playtime_num, rating_num, year, price, _) = row

                playtime_str = format_duration(playtime_num)
                rating_str = f"{rating_num} ★" if rating_num else "N/A"
                year_str = int(year) if year else "N/A"
                price_str = f"${price:.2f}" if price is not None else "N/A"

                self.search_results_data.append(row)

                self.tree.insert("", "end", values=(
                    game_id, title, year_str, price_str, platforms, devs, pubs,
                    playtime_num, playtime_str, esrb, rating_num, rating_str
                ))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to search games: {e}")
            self.controller.conn.rollback()

    # Sorts the treeview by a column without re-querying.
    def sort_column(self, col, reverse):
        try:
            if col == "My Playtime":
                data = [(float(self.tree.set(item, "My PlaytimeNum")), item) for item in self.tree.get_children('')]
            elif col == "My Rating":
                data = [(float(self.tree.set(item, "My RatingNum") or -1), item) for item in self.tree.get_children('')]
            elif col == "Year":
                data = [(float(self.tree.set(item, col) if self.tree.set(item, col) != "N/A" else 0), item) for item in
                        self.tree.get_children('')]
            elif col == "Price":
                data = []
                for item in self.tree.get_children(''):
                    price_val = self.tree.set(item, col)
                    if price_val == "N/A":
                        data.append((-1.0, item))
                    else:
                        data.append((float(price_val.replace("$", "")), item))
            else:
                data = [(self.tree.set(item, col).lower(), item) for item in self.tree.get_children('')]
        except Exception as e:
            print(f"Sort error: {e}")
            return

        data.sort(reverse=reverse)

        for index, (val, item) in enumerate(data):
            self.tree.move(item, '', index)

        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    # Helper to get the GameID and Title of the selected item.
    def get_selected_game(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a game from the search results.")
            return None, None

        item_data = self.tree.item(selected_item)
        game_id = item_data['values'][0]
        game_title = item_data['values'][1]
        return game_id, game_title

    # Adds the selected game to a user-chosen collection.
    def add_to_collection(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        try:
            # CORRECTED: "PlatformID", "UserPlatform", "UserID" -> platformid, userplatform, userid
            self.controller.curs.execute(
                'SELECT platformid FROM userplatform WHERE userid = %s',
                (self.controller.current_user_id,)
            )
            user_platforms = {row[0] for row in self.controller.curs.fetchall()}

            # CORRECTED: "PlatformID", "GamePlatform", "GameID" -> platformid, gameplatform, gameid
            self.controller.curs.execute(
                'SELECT platformid FROM gameplatform WHERE gameid = %s',
                (game_id,)
            )
            game_platforms = {row[0] for row in self.controller.curs.fetchall()}

            if user_platforms.isdisjoint(game_platforms):
                if not messagebox.askyesno("Platform Warning",
                                           f"Warning: You do not own any of the platforms for '{game_title}'.\n\n"
                                           "Do you still want to add it to a collection?"):
                    return

        except Exception as e:
            messagebox.showerror("Database Error", f"Could not verify platforms: {e}")
            self.controller.conn.rollback()
            return

        try:
            # CORRECTED: "CollectionID", "Name", "Collection", "UserID", "Name" ->
            # collectionid, name, collection, userid, name
            self.controller.curs.execute(
                'SELECT collectionid, name FROM collection WHERE userid = %s ORDER BY name',
                (self.controller.current_user_id,)
            )
            collections = self.controller.curs.fetchall()
            if not collections:
                messagebox.showerror("Error", "You have no collections. Please create one first.")
                return

            collection_names = [name for cid, name in collections]
            choice = self.show_choice_dialog("Add to Collection",
                                             f"Add '{game_title}' to which collection?",
                                             collection_names)

            if choice:
                chosen_collection_id = [cid for cid, name in collections if name == choice][0]

                # CORRECTED: "CollectionGame", "CollectionID", "GameID" -> collectiongame, collectionid, gameid
                self.controller.curs.execute(
                    'INSERT INTO collectiongame (collectionid, gameid) VALUES (%s, %s)',
                    (chosen_collection_id, game_id)
                )
                self.controller.conn.commit()
                messagebox.showinfo("Success", f"Added '{game_title}' to '{choice}'.")
                self.controller.frames["MainAppFrame"].collections_frame.load_collections()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", f"'{game_title}' is already in that collection.")
            else:
                messagebox.showerror("Database Error", f"Failed to add game: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

    # A custom simple dialog to pick from a list.
    def show_choice_dialog(self, title, text, options):
        dialog = tk.Toplevel(self.controller)
        dialog.title(title)
        dialog.transient(self.controller)
        dialog.grab_set()

        ttk.Label(dialog, text=text, font=("Arial", 12)).pack(padx=20, pady=(20, 10))

        choice_var = tk.StringVar(dialog)

        if options:
            choice_var.set(options[0])
            dropdown = ttk.OptionMenu(dialog, choice_var, options[0], *options)
            dropdown.pack(padx=20, pady=10, fill="x")

        result = [None]

        def on_ok():
            result[0] = choice_var.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        ttk.Button(button_frame, text="OK", command=on_ok).pack(side="left", padx=10)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side="right", padx=10)
        button_frame.pack(padx=20, pady=(10, 20))

        self.controller.wait_window(dialog)
        return result[0]

    # Rates the selected game.
    def rate_game(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        rating = simpledialog.askinteger("Rate Game", f"Enter your rating (1-5) for '{game_title}':", minvalue=1,
                                         maxvalue=5)
        if not rating:
            return

        try:
            # CORRECTED: All tables and columns to lowercase
            sql = """
                INSERT INTO purchases (userid, gameid, starrating)
                VALUES (%s, %s, %s)
                ON CONFLICT (userid, gameid) 
                DO UPDATE SET starrating = EXCLUDED.starrating;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, game_id, rating))
            self.controller.conn.commit()
            messagebox.showinfo("Success", f"Set rating for '{game_title}' to {rating} stars.")

            self.search_games()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to rate game: {e}")

    # Logs a play session for the selected game.
    def play_game(self):
        game_id, game_title = self.get_selected_game()
        if not game_id:
            return

        duration = simpledialog.askinteger("Log Play Session", f"How many minutes did you play '{game_title}'?",
                                           minvalue=1)
        if not duration:
            return

        try:
            # CORRECTED: "Plays" and all columns to lowercase
            sql = """
                INSERT INTO plays (userid, gameid, playdatetime, duration)
                VALUES (%s, %s, %s, %s)
            """
            self.controller.curs.execute(sql,
                                         (self.controller.current_user_id, game_id, datetime.datetime.now(), duration))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"Logged {duration} minutes for '{game_title}'.")

            self.search_games()
            self.controller.frames["MainAppFrame"].collections_frame.load_collections()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to log play session: {e}")


# The frame for the "Social" tab.
class SocialFrame(ttk.Frame):
    # Initializes the social UI (search, follow, unfollow).
    def __init__(self, parent, controller):
        ttk.Frame.__init__(self, parent, padding="10")
        self.controller = controller

        find_frame = ttk.Frame(self, padding="10")
        find_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ttk.Label(find_frame, text="Find Users", font=("Arial", 16)).pack(pady=10)

        search_bar = ttk.Frame(find_frame)
        search_bar.pack(fill="x")

        ttk.Label(search_bar, text="Search by Email:").pack(side="left")
        self.email_entry = ttk.Entry(search_bar, width=30)
        self.email_entry.pack(side="left", padx=5, expand=True)
        ttk.Button(search_bar, text="Search", command=self.search_users).pack(side="left")

        cols_search = ("Username", "Email")
        self.search_tree = ttk.Treeview(find_frame, columns=cols_search, show="headings")
        self.search_tree.heading("Username", text="Username")
        self.search_tree.heading("Email", text="Email")
        self.search_tree.column("Username", width=120)
        self.search_tree.column("Email", width=200)

        self.search_tree['displaycolumns'] = ("Username", "Email")
        self.search_tree["columns"] = ("UserID", "Username", "Email")
        self.search_tree.column("UserID", width=0, stretch=tk.NO)

        self.search_tree.pack(fill="both", expand=True, pady=(10, 0))

        ttk.Button(find_frame, text="Follow Selected User", command=self.follow_user).pack(pady=10)

        following_frame = ttk.Frame(self, padding="10")
        following_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        ttk.Label(following_frame, text="Following", font=("Arial", 16)).pack(pady=10)

        cols_following = ("Username", "Email", "Follow Date")
        self.following_tree = ttk.Treeview(following_frame, columns=cols_following, show="headings")
        self.following_tree.heading("Username", text="Username")
        self.following_tree.heading("Email", text="Email")
        self.following_tree.heading("Follow Date", text="Follow Date")
        self.following_tree.column("Username", width=120)
        self.following_tree.column("Email", width=200)
        self.following_tree.column("Follow Date", width=100)

        self.following_tree['displaycolumns'] = ("Username", "Email", "Follow Date")
        self.following_tree["columns"] = ("UserID", "Username", "Email", "Follow Date")
        self.following_tree.column("UserID", width=0, stretch=tk.NO)

        self.following_tree.pack(fill="both", expand=True)

        ttk.Button(following_frame, text="Unfollow Selected User", command=self.unfollow_user).pack(pady=10)

    # Finds users by email.
    def search_users(self):
        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        email_query = self.email_entry.get()
        if not email_query:
            return

        try:
            # CORRECTED: "UserID", "Username", "Email", "User" -> userid, username, email, users
            sql = """
                SELECT userid, username, email 
                FROM users 
                WHERE email ILIKE %s AND userid != %s
            """
            self.controller.curs.execute(sql, (f"%{email_query}%", self.controller.current_user_id))

            for row in self.controller.curs.fetchall():
                self.search_tree.insert("", "end", values=row)

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to search users: {e}")
            self.controller.conn.rollback()

    # Loads the list of users the current user is following.
    def load_following(self):
        for item in self.following_tree.get_children():
            self.following_tree.delete(item)

        if not self.controller.current_user_id:
            return

        try:
            # CORRECTED: All tables and columns to lowercase
            sql = """
                SELECT u.userid, u.username, u.email, f.followdate
                FROM follows f
                JOIN users u ON f.followedid = u.userid
                WHERE f.followerid = %s
                ORDER BY u.username ASC;
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id,))

            for row in self.controller.curs.fetchall():
                user_id, username, email, follow_date = row
                date_str = follow_date.strftime("%Y-%m-%d") if follow_date else "N/A"
                self.following_tree.insert("", "end", values=(user_id, username, email, date_str))

        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load following list: {e}")
            self.controller.conn.rollback()

    # Follows the user selected in the search results.
    def follow_user(self):
        selected_item = self.search_tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a user from the search results to follow.")
            return

        user_id, username, _ = self.search_tree.item(selected_item)['values']

        try:
            # CORRECTED: "Follows", "FollowerID", "FollowedID", "FollowDate" -> follows, followerid, followedid, followdate
            sql = """
                INSERT INTO follows (followerid, followedid, followdate)
                VALUES (%s, %s, %s)
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, user_id, datetime.datetime.now()))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"You are now following {username}.")
            self.load_following()

        except psycopg.Error as e:
            self.controller.conn.rollback()
            if e.diag.sqlstate == '23505':
                messagebox.showerror("Error", f"You are already following {username}.")
            else:
                messagebox.showerror("Database Error", f"Failed to follow user: {e}")

    # Unfollows the user selected in the "Following" list.
    def unfollow_user(self):
        selected_item = self.following_tree.focus()
        if not selected_item:
            messagebox.showwarning("Warning", "Please select a user from your 'Following' list to unfollow.")
            return

        user_id, username, _, _ = self.following_tree.item(selected_item)['values']

        if not messagebox.askyesno("Confirm", f"Are you sure you want to unfollow {username}?"):
            return

        try:
            # CORRECTED: "Follows", "FollowerID", "FollowedID" -> follows, followerid, followedid
            sql = """
                DELETE FROM follows 
                WHERE followerid = %s AND followedid = %s
            """
            self.controller.curs.execute(sql, (self.controller.current_user_id, user_id))
            self.controller.conn.commit()

            messagebox.showinfo("Success", f"You have unfollowed {username}.")
            self.load_following()

        except Exception as e:
            self.controller.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to unfollow user: {e}")


# Main execution block to run the application.
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()