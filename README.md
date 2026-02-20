# SpotifAgent

SpotifAgent is an assistant for your music provider account, built with Python, FastAPI and Typer.

Its main goal is to provide you recommendations based on your listen history.
These recommendations are pushed into new dedicated playlists.

For now, **only [Spotify](https://open.spotify.com/) is supported**.

## Requirements

To work with this project, you will need the following tools installed on your machine:

*   **Python**: 3.13
*   **Poetry**: 1.8.5
*   **Docker Compose**: v2
*   **Spotify Developer Account**: You need a Spotify account and access to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
*   **Spotify App**: Create an app in the Spotify Developer Dashboard to get a `Client ID` and `Client Secret`.

## Installation

Follow these steps to set up the project locally:

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/ychab/spotifagent
    cd spotifagent
    ```

2.  **Install dependencies:**

    Use Poetry to install the project dependencies.

    ```bash
    make install
    ```

3.  **Install pre-commit hooks:**

    ```bash
    poetry run pre-commit install
    ```

## Configuration

Before running the application, you need to configure the environment variables and your Spotify App.

1.  **Environment Variables:**

    Copy the example environment file and configure it with your settings.

    ```bash
    cp .env.DIST .env
    ```

    Open `.env` and fill in the required values:
    *   `SPOTIFY_CLIENT_ID`: Your Spotify App Client ID.
    *   `SPOTIFY_CLIENT_SECRET`: Your Spotify App Client Secret.
    *   `SPOTIFAGENT_SECRET_KEY`: A secret key for the application (min 32 characters).
    *   Database settings if you want to customize them (defaults are usually fine for local development with Docker).

2.  **Spotify App Configuration:**

    You must add the redirect URI to your Spotify App settings in the Developer Dashboard.

    *   Go to your app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
    *   Click on "Edit Settings".
    *   Under "Redirect URIs", add the callback URL.
    *   By default, the application uses: `http://127.0.0.1:8000/api/v1/spotify/callback`
    *   Ensure this matches the `SPOTIFY_REDIRECT_URI` in your `.env` configuration (or the default if not set).

## Running the Application

You can run the application and the database using Docker Compose or the provided Makefile.

**Using Makefile:**

```bash
make up
```

This command will start the database and the application containers.

**Using Docker Compose directly:**

```bash
docker compose up -d
```

## CLI User Guide

SpotifAgent provides a Command Line Interface (CLI) to manage users and interact with Spotify.

To use the CLI, you can use the `spotifagent` command if installed in your environment, or run it via Poetry:

```bash
poetry run spotifagent [COMMAND]
```

### Global Options

*   `--log-level`, `-l`: Set the logging level (e.g., DEBUG, INFO, WARNING, ERROR).
*   `--log-handlers`: Set the logging handlers.
*   `--version`, `-v`: Show the application's version and exit.
*   `--help`: Show help message.

### User Management (`users`)

Manage application users.

**Create a user:**

```bash
poetry run spotifagent users create --email <email>
```
You will be prompted to enter and confirm the password.

**Update a user:**

```bash
poetry run spotifagent users update <user_id> --email <new_email> --password <new_password>
```

### Spotify Interaction (`spotify`)

Interact with Spotify data.

**Connect a user to Spotify:**

Initiates the OAuth flow. You need to open the URL in a browser and authorize the app.

**Prerequisite:** The FastAPI application must be running to handle the Spotify callback.
Ensure you have started the application (e.g., using `make up`) before running this command.

```bash
poetry run spotifagent spotify connect --email <email>
```

*   `--timeout`: Seconds to wait for authentication (default: 60.0).
*   `--poll-interval`: Seconds between status checks (default: 2.0).

**Sync Spotify data:**

Synchronize the user's items (artists, tracks) into the database.

```bash
poetry run spotifagent spotify sync --email <email> [OPTIONS]
```

**Sync Options:**

*   `--sync` / `--no-sync`: Sync all user's items.
*   `--purge` / `--no-purge`: Purge all user's items before syncing.
*   `--sync-artist-top`: Sync user's top artists.
*   `--sync-track-top`: Sync user's top tracks.
*   `--sync-track-saved`: Sync user's saved tracks.
*   `--sync-track-playlist`: Sync user's playlist tracks.
*   `--page-limit`: Items to fetch per page (default: 50).
*   `--time-range`: Time range for top items (short_term, medium_term, long_term).
*   `--batch-size`: Number of items to bulk upsert (default: 300).

Example: Sync everything for a user

```bash
poetry run spotifagent spotify sync --email user@example.com --sync
```

## Development

To run tests:

```bash
make test
```
