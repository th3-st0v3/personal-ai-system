from db import add_note, get_notes, search_notes
from model import ask_model


while True:
    print("1. Add a note")
    print("2. View notes")
    print("3. Search notes")
    print("4. Ask AI")
    print("5. Quit")

    choice = input("Choose an option: ")

    if choice == "1":
        note = input("Enter a note: ")
        add_note(note)
        print("Note saved.")

    elif choice == "2":
        notes = get_notes()

        print("\nYour notes:")

        for note in notes:
            print(f"{note[0]}. {note[1]}")
            print(f"   {note[3]}")

    elif choice == "3":
        query = input("Search for: ")
        notes = search_notes(query)

        print("\nSearch results:")

        for note in notes:
            print(f"{note[0]}. {note[1]}")
            print(f"   {note[3]}")

    elif choice == "4":
        prompt = input("Ask the AI: ")

        try:
            answer = ask_model(prompt)

            print("\nAI:")
            print(answer)

        except Exception as error:
            print(f"\nAI request failed: {error}")

    elif choice == "5":
        print("Goodbye.")
        break

    else:
        print("Invalid option. Please choose 1, 2, 3, 4, or 5.")